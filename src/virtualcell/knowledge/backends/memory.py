"""In-memory KnowledgeStore backend.

Pure Python, zero external dependencies. This is the default backend and the one
exercised by the test suite. It is suitable for demos, tests, and small graphs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import NamedTuple

from virtualcell.knowledge.schema import SYMMETRIC_RELATIONS, BioEntity, Interaction
from virtualcell.knowledge.store import Edge


class _Adjacent(NamedTuple):
    """One stored adjacency: an interaction as seen from one of its two endpoints.

    Provenance is kept here rather than reconstructed from ``_interactions`` on lookup.
    It used to be dropped at insertion, so ``edges()`` could not have returned it at any
    price; a scan of every interaction per neighbour query would be the alternative.
    """

    relation: str
    neighbor_id: str
    confidence: float
    forward: bool
    evidence: tuple[str, ...]
    study_id: str | None


class InMemoryKnowledgeStore:
    """A dict-backed implementation of the KnowledgeStore protocol."""

    def __init__(self) -> None:
        self._entities: dict[str, BioEntity] = {}
        # adjacency: entity_id -> the interactions incident to it, one entry per direction
        self._edges: dict[str, list[_Adjacent]] = defaultdict(list)
        # original interactions, kept so the graph can be serialized losslessly
        self._interactions: list[Interaction] = []

    def upsert(self, entity: BioEntity) -> None:
        self._entities[entity.id] = entity

    def add_interaction(self, interaction: Interaction) -> None:
        if interaction.source_id not in self._entities:
            raise KeyError(f"unknown source entity: {interaction.source_id}")
        if interaction.target_id not in self._entities:
            raise KeyError(f"unknown target entity: {interaction.target_id}")
        self._interactions.append(interaction)
        rel = interaction.relation.value
        conf = interaction.confidence
        symmetric = interaction.relation in SYMMETRIC_RELATIONS
        evidence = tuple(interaction.evidence)
        study = interaction.study_id
        # Forward edge (source -> target) always follows the relation's arrow.
        self._edges[interaction.source_id].append(
            _Adjacent(rel, interaction.target_id, conf, True, evidence, study)
        )
        # Reverse edge (target -> source): a real forward step only if symmetric;
        # otherwise stored for undirected neighbour queries but marked reverse. Provenance
        # is a property of the fact, not of the direction it is read in, so it is the same
        # on both entries.
        self._edges[interaction.target_id].append(
            _Adjacent(rel, interaction.source_id, conf, symmetric, evidence, study)
        )

    def get(self, entity_id: str) -> BioEntity | None:
        return self._entities.get(entity_id)

    def all_entities(self) -> list[BioEntity]:
        """Return every entity (used for serialization)."""
        return list(self._entities.values())

    def all_interactions(self) -> list[Interaction]:
        """Return every original interaction (used for serialization)."""
        return list(self._interactions)

    def neighbors(self, entity_id: str, relation: str | None = None) -> list[BioEntity]:
        out: list[BioEntity] = []
        seen: set[str] = set()
        for adjacent in self._edges.get(entity_id, []):
            if relation is not None and adjacent.relation != relation:
                continue
            neighbor_id = adjacent.neighbor_id
            if neighbor_id in seen:
                continue
            seen.add(neighbor_id)
            entity = self._entities.get(neighbor_id)
            if entity is not None:
                out.append(entity)
        return out

    def edges(
        self, entity_id: str, relation: str | None = None, direction: str = "forward"
    ) -> list[Edge]:
        out: list[Edge] = []
        for adjacent in self._edges.get(entity_id, []):
            if relation is not None and adjacent.relation != relation:
                continue
            if direction == "forward" and not adjacent.forward:
                continue
            if adjacent.neighbor_id not in self._entities:
                continue
            out.append(
                Edge(
                    relation=adjacent.relation,
                    target_id=adjacent.neighbor_id,
                    confidence=adjacent.confidence,
                    forward=adjacent.forward,
                    evidence=list(adjacent.evidence),
                    study_id=adjacent.study_id,
                )
            )
        return out

    def search(self, query: str, k: int = 10) -> list[BioEntity]:
        """Case-insensitive substring ranking over each entity's text."""
        q = query.lower().strip()
        if not q:
            return []
        scored: list[tuple[int, BioEntity]] = []
        for entity in self._entities.values():
            haystack = entity.text().lower()
            if q in haystack:
                # crude score: exact name match ranks highest, then alias, then text
                score = 0
                if entity.name.lower() == q:
                    score = 3
                elif q in entity.name.lower():
                    score = 2
                else:
                    score = 1
                scored.append((score, entity))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entity for _, entity in scored[:k]]
