"""Grounded question answering over the knowledge graph.

The answerer (1) retrieves entities relevant to a natural-language question, (2)
expands them with their immediate graph neighbours, (3) turns everything into
evidence-graded facts, and (4) asks an :class:`~virtualcell.reasoning.llm.LLMBackend`
to synthesize an answer *from that evidence only*. Because every fact carries a
knowledge-base citation and an evidence tier, answers stay grounded and auditable.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.schema import BioEntity
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.llm import LLMBackend, get_backend

# Minimal stopword set for extracting searchable terms from a question.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "do", "does", "did", "what", "which", "who", "whom",
    "how", "why", "when", "where", "whats", "it", "its", "this", "that", "these", "those",
    "into", "from", "as", "at", "by", "about", "tell", "me", "you", "i", "we", "they",
    "he", "she", "them", "his", "her", "their", "our", "your", "my", "can", "could",
    "would", "should", "will", "if", "then",
})

# Retrieval / grounding bounds, to keep the evidence block focused and prompts small.
_MAX_SEED_ENTITIES = 8
_MAX_EXPANDED_SEEDS = 3
_MAX_NEIGHBORS_PER_SEED = 6


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

    def __init__(self, store: KnowledgeStore, backend: LLMBackend | None = None) -> None:
        self.store = store
        self.backend = backend or get_backend()

    def retrieve(self, question: str, k: int = 5) -> list[BioEntity]:
        """Return entities relevant to the question, de-duplicated and capped."""
        seen: dict[str, BioEntity] = {}
        for term in _terms(question):
            for entity in self.store.search(term, k=k):
                seen.setdefault(entity.id, entity)
                if len(seen) >= _MAX_SEED_ENTITIES:
                    return list(seen.values())
        return list(seen.values())

    def _ground(self, seeds: list[BioEntity]) -> list[GroundedFact]:
        facts: list[GroundedFact] = []
        seen_ids: set[str] = {e.id for e in seeds}

        for entity in seeds:
            desc = f" - {entity.description}" if entity.description else ""
            facts.append(
                GroundedFact(
                    statement=(
                        f"{entity.type.value.capitalize()} '{entity.name}' "
                        f"(id={entity.id}){desc}"
                    ),
                    # Presence in the curated knowledge base is treated as established.
                    tier=EvidenceTier.ESTABLISHED,
                    citation=f"kb:{entity.id}",
                )
            )

        # Expand the top few seeds with their neighbours to give relational context.
        for entity in seeds[:_MAX_EXPANDED_SEEDS]:
            for neighbor in self.store.neighbors(entity.id)[:_MAX_NEIGHBORS_PER_SEED]:
                facts.append(
                    GroundedFact(
                        statement=(
                            f"'{entity.name}' (id={entity.id}) is connected to "
                            f"{neighbor.type.value} '{neighbor.name}' (id={neighbor.id}) "
                            "in the knowledge graph."
                        ),
                        tier=EvidenceTier.ESTABLISHED,
                        citation=f"kb:{entity.id}->kb:{neighbor.id}",
                    )
                )
                seen_ids.add(neighbor.id)
        return facts

    @staticmethod
    def _render(facts: list[GroundedFact]) -> str:
        return "\n".join(
            f"{i}. [{f.tier.value}] {f.statement} [{f.citation}]"
            for i, f in enumerate(facts, start=1)
        )

    def answer(self, question: str, k: int = 5) -> Answer:
        seeds = self.retrieve(question, k=k)
        if not seeds:
            return Answer(
                question=question,
                answer=(
                    "No knowledge-base entity matched this question, so there is no "
                    "grounded evidence to answer it. Try ingesting relevant data first."
                ),
                backend=self.backend.name,
            )

        facts = self._ground(seeds)
        evidence = self._render(facts)
        text = self.backend.answer(question, evidence)
        return Answer(
            question=question,
            answer=text,
            backend=self.backend.name,
            grounded_entity_ids=[e.id for e in seeds],
            facts=facts,
        )
