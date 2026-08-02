"""Integrated evidence-query orchestrator (PR9).

One entry point that unifies two evidence sources while keeping their epistemic status
distinct:

1. the curated **knowledge base** (established, high-confidence facts), and
2. **literature** discovered on demand when the KB has no answer — extracted, verified,
   converted to canonical runs and ingested as *weak, pending-review* evidence (PR8b–e).

The flow is: KB lookup → if it grounds the question, answer from the KB (the
:class:`QuestionAnswerer` path) → otherwise, on a **miss**, consult literature, ingest
what survives verification into the same store, and surface it as clearly weak,
provenance-carrying evidence for review. This is a *separate* orchestrator layered over
the existing pieces — it does not bolt a literature fallback into ``qa.py``.

**Epistemic invariant.** A weak literature measurement is never presented as an
established fact, in the structured facts *or* in the natural-language answer. On a
curated hit the orchestrator grounds (which classifies), partitions curated from
literature, and only *then* asks the answerer to synthesize from those classified facts —
so the backend's evidence block and the reported facts carry identical tiers. Literature
evidence is never hidden: it stays visible, labelled, and capped at ``HYPOTHESIS``.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

from virtualcell.core.contracts import AgentInput
from virtualcell.core.evidence import EvidenceTier, is_unreviewed
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.literature.contracts import LiteratureEvidenceBundle
from virtualcell.literature.ingestion import (
    LITERATURE_EVIDENCE_CONFIDENCE,
    IngestionReport,
    ingest_runs,
)
from virtualcell.literature.resolution import ResolutionReport, resolve_literature_markers
from virtualcell.reasoning.llm import LLMBackend
from virtualcell.reasoning.qa import GroundedFact, QuestionAnswerer

_LIT_PREFIX = "lit:"
_LIT_ASSAY = "lit:assay:"


class QuerySource(StrEnum):
    """Where the answer's evidence came from."""

    KNOWLEDGE_BASE = "knowledge_base"
    LITERATURE_AUGMENTED = "literature_augmented"
    NO_EVIDENCE = "no_evidence"


class OrchestratedAnswer(BaseModel):
    """A unified answer that keeps established KB facts and weak literature evidence apart."""

    question: str
    source: QuerySource
    answer: str
    backend: str | None = None
    kb_entity_ids: list[str] = Field(default_factory=list)
    kb_facts: list[GroundedFact] = Field(default_factory=list)
    literature_consulted: bool = False
    literature_facts: list[GroundedFact] = Field(default_factory=list)
    ingestion: IngestionReport | None = None
    resolution: ResolutionReport | None = None
    # The discovery run's own outcome (``success``/``zero_results``/``provider_error``)
    # when literature was consulted. Carried so a caller can tell "we could not look"
    # from "we looked and found nothing" — the two must never be conflated.
    literature_run_status: str | None = None
    # Per-document fetch failures during an otherwise successful *search*. A search can
    # succeed while every document behind it times out; without this the run would look
    # like a genuine zero-result.
    literature_document_failure: str | None = None


def _is_target_token(token: str) -> bool:
    """A gene/marker-like symbol: an all-caps symbol (``TERT``, ``CDK4``) or one carrying
    a digit (``p16``, ``p21``, ``PGC1A``). Deliberately conservative — an ordinary
    Capitalized word (``What``) or a bare number is not a target."""
    if len(token) < 2 or not any(ch.isalpha() for ch in token):
        return False
    return token.isupper() or any(ch.isdigit() for ch in token)


def _derive_targets(question: str) -> list[str]:
    """Extract gene/marker-like measurement targets from a question, order-preserving."""
    targets: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]+", question):
        if _is_target_token(token) and token not in targets:
            targets.append(token)
    return targets


class EvidenceQueryOrchestrator:
    """Answers a question from the KB, reaching for literature only when the KB misses."""

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        answerer: QuestionAnswerer | None = None,
        literature_agent: object | None = None,
        backend: LLMBackend | None = None,
    ) -> None:
        self.store = store
        self.answerer = answerer or QuestionAnswerer(store, backend=backend)
        # An optional, pre-wired LiteratureDiscoveryAgent (its provider already injected).
        # None disables literature augmentation — the orchestrator is then KB-only.
        self.literature_agent = literature_agent

    async def answer(
        self,
        question: str,
        *,
        target_measurements: list[str] | None = None,
        allow_literature: bool = True,
    ) -> OrchestratedAnswer:
        seeds = self.answerer.retrieve(question)
        # A curated (non-``lit:``) match is an established KB hit; a match on only
        # literature-ingested nodes is *not* — that evidence stays weak.
        curated = [e for e in seeds if not e.id.startswith(_LIT_PREFIX)]
        if curated:
            # Ground (which classifies) -> partition -> only THEN synthesize, so the
            # backend's evidence block and the structured facts below carry exactly the
            # same classification. Synthesizing first would hand the backend literature
            # evidence still labelled established.
            kb_facts, weak_facts = self._partition_facts(self.answerer.ground(seeds))
            grounded = self.answerer.synthesize(
                question, [*kb_facts, *weak_facts], [e.id for e in seeds]
            )
            return OrchestratedAnswer(
                question=question,
                source=QuerySource.KNOWLEDGE_BASE,
                answer=grounded.answer,
                backend=grounded.backend,
                kb_entity_ids=grounded.grounded_entity_ids,
                kb_facts=kb_facts,
                literature_facts=weak_facts,
            )

        # KB miss. If literature evidence for this question was already ingested, surface
        # it as-is rather than re-discovering; otherwise discover it now if allowed.
        existing = self._existing_literature_facts(seeds)
        if existing:
            return self._literature_answer(question, existing, ingestion=None, consulted=False)

        if not (allow_literature and self.literature_agent is not None):
            return OrchestratedAnswer(
                question=question,
                source=QuerySource.NO_EVIDENCE,
                answer=(
                    "No knowledge-base entity matched this question, and literature "
                    "augmentation is not available. There is no grounded evidence to answer it."
                ),
            )

        return await self._augment_with_literature(question, target_measurements)

    async def augment_with_literature(
        self, question: str, target_measurements: list[str] | None = None
    ) -> OrchestratedAnswer:
        """Consult literature directly, bypassing the KB-first gate.

        :meth:`answer` reaches for literature only on a KB *miss*, which is right for
        question answering. A caller that has already reasoned by other means and is
        explicitly asking for supplementary literature (the platform query boundary, with
        ``allow_literature=true``) must not have that request silently skipped just
        because the KB happens to match — so it enters here instead.
        """
        return await self._augment_with_literature(question, target_measurements)

    async def _augment_with_literature(
        self, question: str, target_measurements: list[str] | None
    ) -> OrchestratedAnswer:
        targets = target_measurements or _derive_targets(question)
        # The orchestrator owns ingestion (so it captures the report and controls the
        # store): run the agent through conversion only, then ingest the canonical runs.
        out = await self.literature_agent.run(
            AgentInput(
                query=question,
                context={
                    "extract": True,
                    "verify": True,
                    "convert": True,
                    "target_measurements": targets,
                },
            )
        )
        bundle = LiteratureEvidenceBundle.model_validate(out.result)
        ingestion = ingest_runs(self.store, bundle.canonical_runs)
        # Bridge the newly ingested markers onto curated ontology nodes (weakly), so the
        # evidence is reachable from the known graph without being merged or upgraded.
        resolution = resolve_literature_markers(self.store, ingestion.markers)
        facts = [self._assay_fact(self.store.get(a)) for a in ingestion.assay_results]
        facts = [f for f in facts if f is not None]

        run_status = bundle.run_status.value
        worst = bundle.worst_document_failure
        document_failure = worst.value if worst is not None else None
        if not facts:
            return OrchestratedAnswer(
                question=question,
                source=QuerySource.NO_EVIDENCE,
                answer=(
                    "No knowledge-base entity matched this question. Literature was "
                    "consulted but produced no machine-verified measurement to surface."
                ),
                literature_consulted=True,
                ingestion=ingestion,
                resolution=resolution,
                literature_run_status=run_status,
                literature_document_failure=document_failure,
            )
        return self._literature_answer(
            question,
            facts,
            ingestion=ingestion,
            resolution=resolution,
            consulted=True,
            run_status=run_status,
            document_failure=document_failure,
        )

    def _literature_answer(
        self,
        question: str,
        facts: list[GroundedFact],
        *,
        ingestion: IngestionReport | None,
        consulted: bool,
        resolution: ResolutionReport | None = None,
        run_status: str | None = None,
        document_failure: str | None = None,
    ) -> OrchestratedAnswer:
        rendered = "\n".join(f"- {f.statement} [{f.citation}]" for f in facts)
        return OrchestratedAnswer(
            question=question,
            source=QuerySource.LITERATURE_AUGMENTED,
            answer=(
                "No established knowledge-base answer was found. Literature evidence "
                f"provides {len(facts)} weak measurement(s), pending review, that must be "
                f"confirmed before use (not established biology):\n{rendered}"
            ),
            literature_consulted=consulted,
            literature_facts=facts,
            ingestion=ingestion,
            resolution=resolution,
            literature_run_status=run_status,
            literature_document_failure=document_failure,
        )

    def _existing_literature_facts(self, seeds: list) -> list[GroundedFact]:
        """Weak facts from literature nodes already in the store that the query matched.

        A matched ``lit:`` marker is expanded to the assay measurements associated with
        it, so a repeat query surfaces the previously ingested evidence without
        re-discovering it.
        """
        facts: list[GroundedFact] = []
        seen: set[str] = set()
        for seed in seeds:
            if not seed.id.startswith(_LIT_PREFIX):
                continue
            assays = [seed] if seed.id.startswith(_LIT_ASSAY) else self.store.neighbors(seed.id)
            for node in assays:
                if node.id.startswith(_LIT_ASSAY) and node.id not in seen:
                    seen.add(node.id)
                    fact = self._assay_fact(node)
                    if fact is not None:
                        facts.append(fact)
        return facts

    @staticmethod
    def _partition_facts(
        facts: list[GroundedFact],
    ) -> tuple[list[GroundedFact], list[GroundedFact]]:
        """Split already-classified grounded facts into curated and literature evidence.

        A **pure split for reporting** — it never re-tiers. Tiers are assigned in exactly
        one place, :meth:`QuestionAnswerer.ground`, using the same shared
        :func:`~virtualcell.core.evidence.is_unreviewed` policy applied here, so a fact
        landing in ``weak_facts`` has already been capped at grounding time. Keeping a
        second cap here would be a competing implementation of the same rule.
        """
        kb_facts, weak_facts = [], []
        for fact in facts:
            (weak_facts if is_unreviewed(fact.citation) else kb_facts).append(fact)
        return kb_facts, weak_facts

    @staticmethod
    def _assay_fact(node) -> GroundedFact | None:
        """A weak, provenance-carrying fact from one ``lit:assay:`` node.

        Tagged ``HYPOTHESIS`` (never ``ESTABLISHED``): the source integrity is verified,
        but the *biological* meaning of a single measurement is not — it is evidence for
        review, not a fact.
        """
        if node is None:  # pragma: no cover - defensive
            return None
        props = node.properties
        article = props.get("article_key", "unknown source")
        return GroundedFact(
            statement=(
                f"Literature measurement (weak, {props.get('review_status', 'pending')}): "
                f"{node.name} [source {article}]"
            ),
            tier=EvidenceTier.HYPOTHESIS,
            citation=f"lit:{props.get('candidate_id', node.id)}",
            confidence=LITERATURE_EVIDENCE_CONFIDENCE,
        )
