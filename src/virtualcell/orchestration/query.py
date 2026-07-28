"""Integrated evidence-query orchestrator (PR9).

One entry point that unifies two evidence sources while keeping their epistemic status
distinct:

1. the curated **knowledge base** (established, high-confidence facts), and
2. **literature** discovered on demand when the KB has no answer — extracted, verified,
   converted to canonical runs and ingested as *weak, pending-review* evidence (PR8b–e).

The flow is: KB lookup → if it grounds the question, answer from the KB (unchanged
:class:`QuestionAnswerer` path) → otherwise, on a **miss**, consult literature, ingest
what survives verification into the same store, and surface it as clearly weak,
provenance-carrying evidence for review. This is a *separate* orchestrator layered over
the existing pieces — it does not bolt a literature fallback into ``qa.py`` — and it
never presents a weak literature measurement as an established fact (no LLM synthesis is
run over the weak evidence, so a possibility is never phrased as a conclusion).

Out of scope for this slice (later PR9 work): formatting the deferred mechanism/hypothesis
intents (Q5/Q6/Q9) into ``DecisionReport``s from the KG-explain path, and resolving
``lit:`` markers onto curated ontology nodes.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

from virtualcell.core.contracts import AgentInput
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.literature.contracts import LiteratureEvidenceBundle
from virtualcell.literature.ingestion import (
    LITERATURE_EVIDENCE_CONFIDENCE,
    IngestionReport,
    ingest_runs,
)
from virtualcell.reasoning.llm import LLMBackend
from virtualcell.reasoning.qa import GroundedFact, QuestionAnswerer


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
        curated = [e for e in seeds if not e.id.startswith("lit:")]
        if curated:
            grounded = self.answerer.answer(question)
            kb_facts, weak_facts = self._partition_facts(grounded.facts)
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
        facts = [self._assay_fact(self.store.get(a)) for a in ingestion.assay_results]
        facts = [f for f in facts if f is not None]

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
            )
        return self._literature_answer(question, facts, ingestion=ingestion, consulted=True)

    def _literature_answer(
        self,
        question: str,
        facts: list[GroundedFact],
        *,
        ingestion: IngestionReport | None,
        consulted: bool,
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
            if not seed.id.startswith("lit:"):
                continue
            assays = [seed] if seed.id.startswith("lit:assay:") else self.store.neighbors(seed.id)
            for node in assays:
                if node.id.startswith("lit:assay:") and node.id not in seen:
                    seen.add(node.id)
                    fact = self._assay_fact(node)
                    if fact is not None:
                        facts.append(fact)
        return facts

    def _partition_facts(
        self, facts: list[GroundedFact]
    ) -> tuple[list[GroundedFact], list[GroundedFact]]:
        """Split grounded facts into curated (kept as-is) and literature (downgraded).

        The curated answerer tags every retrieved entity ``ESTABLISHED``; a fact citing a
        ``lit:`` node is literature evidence and must not inherit that tier, so it is
        moved out and weakened to ``HYPOTHESIS``.
        """
        kb_facts, weak_facts = [], []
        for fact in facts:
            if "lit:" in fact.citation:
                weak_facts.append(
                    fact.model_copy(
                        update={
                            "tier": EvidenceTier.HYPOTHESIS,
                            "confidence": min(fact.confidence, LITERATURE_EVIDENCE_CONFIDENCE),
                        }
                    )
                )
            else:
                kb_facts.append(fact)
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
