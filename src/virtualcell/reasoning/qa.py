"""Grounded question answering over the knowledge graph.

The answerer (1) retrieves entities relevant to a natural-language question, (2)
traces evidence-graded mechanistic paths from them with :func:`explain`, (3) turns
everything into evidence-graded facts, and (4) asks an
:class:`~virtualcell.reasoning.llm.LLMBackend` to synthesize an answer *from that
evidence only*. Because every fact carries a knowledge-base citation, an evidence
tier (downgraded for multi-hop inferences), and the path that justifies it,
answers stay grounded, auditable, and able to explain *why* and *through which
pathway*.

**Classification precedes synthesis.** :meth:`QuestionAnswerer.ground` assigns every
fact's tier *before* :meth:`QuestionAnswerer.synthesize` renders the evidence block for a
backend, so a backend can never be handed unreviewed evidence labelled as established
truth — and the natural-language answer always carries the same classification as the
structured facts. Splitting the two also lets a caller (the evidence orchestrator)
re-partition classified facts without duplicating rendering or tier logic.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from virtualcell.core.evidence import UNREVIEWED_TIER, EvidenceTier, is_unreviewed
from virtualcell.knowledge.schema import BioEntity
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.explain import explain
from virtualcell.reasoning.llm import LLMBackend, get_backend

# Minimal stopword set for extracting searchable terms from a question.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "do",
        "does",
        "did",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "why",
        "when",
        "where",
        "whats",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "into",
        "from",
        "as",
        "at",
        "by",
        "about",
        "tell",
        "me",
        "you",
        "i",
        "we",
        "they",
        "he",
        "she",
        "them",
        "his",
        "her",
        "their",
        "our",
        "your",
        "my",
        "can",
        "could",
        "would",
        "should",
        "will",
        "if",
        "then",
    }
)

# Retrieval / grounding bounds, to keep the evidence block focused and prompts small.
_MAX_SEED_ENTITIES = 8
_MAX_EXPANDED_SEEDS = 3
_MAX_REACH_PER_SEED = 6
_DEFAULT_MAX_HOPS = 2

# --- unreviewed evidence -----------------------------------------------------
#
# Some nodes in the graph are *proposed* evidence awaiting human review rather than
# curated knowledge — today, literature measurements ingested under the ``lit:`` namespace
# (PR8e). Whether a node is provisional is decided by the single shared policy predicate
# :func:`~virtualcell.core.evidence.is_unreviewed`, which checks both the reserved id
# namespace *and* an explicit ``review_status`` marker; this module never re-implements
# that rule, and needs no dependency on the literature pipeline to apply it.
#
# Such evidence is never ESTABLISHED: an unreviewed fact (or a path touching one) is
# capped and explicitly labelled, so it stays visible as evidence but can never be
# presented — to a user or to an LLM backend — as curated truth.
UNREVIEWED_CONFIDENCE = 0.3
UNREVIEWED_LABEL = "unreviewed literature evidence, pending review"
_ESTABLISHED_CONFIDENCE = 0.8
_NO_EVIDENCE_ANSWER = (
    "No knowledge-base entity matched this question, so there is no "
    "grounded evidence to answer it. Try ingesting relevant data first."
)


def _weaker(a: EvidenceTier, b: EvidenceTier) -> EvidenceTier:
    return a if a.rank <= b.rank else b


class GroundedFact(BaseModel):
    """A single knowledge-base fact backing an answer."""

    statement: str
    tier: EvidenceTier
    citation: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class Answer(BaseModel):
    """The result of answering a question."""

    question: str
    answer: str
    backend: str
    grounded_entity_ids: list[str] = Field(default_factory=list)
    facts: list[GroundedFact] = Field(default_factory=list)


def _terms(question: str) -> list[str]:
    """Extract candidate search terms from a question (plus the whole question)."""
    tokens = re.findall(r"[A-Za-z0-9]+", question)
    terms = [t for t in tokens if len(t) >= 2 and t.lower() not in _STOPWORDS]
    # The full question first (may match a description), then individual terms.
    return [question, *terms]


class QuestionAnswerer:
    """Answers natural-language questions grounded in a :class:`KnowledgeStore`."""

    def __init__(
        self,
        store: KnowledgeStore,
        backend: LLMBackend | None = None,
        max_hops: int = _DEFAULT_MAX_HOPS,
    ) -> None:
        self.store = store
        self.backend = backend or get_backend()
        self.max_hops = max_hops

    def retrieve(self, question: str, k: int = 5) -> list[BioEntity]:
        """Return entities relevant to the question, de-duplicated and capped."""
        seen: dict[str, BioEntity] = {}
        for term in _terms(question):
            for entity in self.store.search(term, k=k):
                seen.setdefault(entity.id, entity)
                if len(seen) >= _MAX_SEED_ENTITIES:
                    return list(seen.values())
        return list(seen.values())

    def ground(self, seeds: list[BioEntity]) -> list[GroundedFact]:
        """Turn retrieved entities into evidence-graded facts.

        Classification happens **here**, before anything is rendered or sent to a backend:
        a curated node is ``ESTABLISHED``, while an unreviewed node — or a path that
        starts or ends on one — is capped at :data:`UNREVIEWED_TIER` and labelled. The
        evidence block a backend later receives therefore cannot present unreviewed
        evidence as established, and the structured facts a caller reports are the very
        same objects.
        """
        facts: list[GroundedFact] = []

        # 1) Direct presence of each retrieved entity: curated => established, unreviewed
        #    (e.g. literature-ingested) => capped and explicitly labelled.
        for entity in seeds:
            desc = f" - {entity.description}" if entity.description else ""
            citation = f"kb:{entity.id}"
            # Every anchor this fact rests on: the node (its id namespace *and* review
            # marker) plus the citation about to be rendered. Any one of them being
            # provisional caps the fact.
            unreviewed = is_unreviewed(entity, citation)
            note = f" [{UNREVIEWED_LABEL}]" if unreviewed else ""
            facts.append(
                GroundedFact(
                    statement=(
                        f"{entity.type.value.capitalize()} '{entity.name}' "
                        f"(id={entity.id}){desc}{note}"
                    ),
                    tier=UNREVIEWED_TIER if unreviewed else EvidenceTier.ESTABLISHED,
                    citation=citation,
                    confidence=(UNREVIEWED_CONFIDENCE if unreviewed else _ESTABLISHED_CONFIDENCE),
                )
            )

        # 2) Directed, evidence-graded mechanistic reach from the top seeds. A direct
        #    edge stays established; multi-hop inferences are downgraded, and the path
        #    that justifies each is carried through so the answer can explain "why".
        #    A path anchored on unreviewed evidence at either end is capped too — the
        #    inference is only as strong as the weakest node it rests on.
        for entity in seeds[:_MAX_EXPANDED_SEEDS]:
            reach = explain(
                self.store, entity.id, max_hops=self.max_hops, top_k=_MAX_REACH_PER_SEED
            )
            seed_unreviewed = is_unreviewed(entity)
            for link in reach.links:
                citation = f"kb:{entity.id}->kb:{link.target_id}"
                # Both path endpoints (by id *and* review marker, so a target that is
                # missing from the store or unflagged is still caught by its namespace)
                # plus the composed citation.
                unreviewed = seed_unreviewed or is_unreviewed(
                    link.target_id, self.store.get(link.target_id), citation
                )
                note = f" [{UNREVIEWED_LABEL}]" if unreviewed else ""
                facts.append(
                    GroundedFact(
                        statement=(
                            f"{entity.name} -> {link.target_name} ({link.hops}-hop): "
                            f"{' | '.join(link.path)}{note}"
                        ),
                        tier=_weaker(link.tier, UNREVIEWED_TIER) if unreviewed else link.tier,
                        citation=citation,
                        confidence=(
                            min(link.confidence, UNREVIEWED_CONFIDENCE)
                            if unreviewed
                            else link.confidence
                        ),
                    )
                )
        return facts

    @staticmethod
    def _render(facts: list[GroundedFact]) -> str:
        return "\n".join(
            f"{i}. [{f.tier.value}] {f.statement} [{f.citation}]"
            for i, f in enumerate(facts, start=1)
        )

    def synthesize(self, question: str, facts: list[GroundedFact], entity_ids: list[str]) -> Answer:
        """Render **already-classified** facts and ask the backend to answer from them.

        Deliberately narrow and separate from :meth:`ground`: a caller that needs to
        re-partition evidence (the evidence orchestrator splits curated from literature)
        classifies first and then synthesizes here, so the natural-language answer and the
        structured facts always agree. Rendering lives only in this method, so no caller
        duplicates the evidence-block format.
        """
        if not facts:
            return Answer(question=question, answer=_NO_EVIDENCE_ANSWER, backend=self.backend.name)
        text = self.backend.answer(question, self._render(facts))
        return Answer(
            question=question,
            answer=text,
            backend=self.backend.name,
            grounded_entity_ids=list(entity_ids),
            facts=list(facts),
        )

    def answer(self, question: str, k: int = 5) -> Answer:
        seeds = self.retrieve(question, k=k)
        if not seeds:
            return Answer(question=question, answer=_NO_EVIDENCE_ANSWER, backend=self.backend.name)
        return self.synthesize(question, self.ground(seeds), [e.id for e in seeds])
