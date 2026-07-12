"""In-memory KnowledgeStore backend.

Pure Python, zero external dependencies. This is the default backend and the one
exercised by the test suite. It is suitable for demos, tests, and small graphs.
"""

from __future__ import annotations

from collections import defaultdict

from virtualcell.knowledge.schema import SYMMETRIC_RELATIONS, BioEntity, Interaction
from virtualcell.knowledge.store import Edge


class InMemoryKnowledgeStore:
    """A dict-backed implementation of the KnowledgeStore protocol."""

    def __init__(self) -> None:
        self._entities: dict[str, BioEntity] = {}
        # adjacency: entity_id -> list of (relation, neighbor_id, confidence, forward)
        self._edges: dict[str, list[tuple[str, str, float, bool]]] = defaultdict(list)
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
        # Forward edge (source -> target) always follows the relation's arrow.
        self._edges[interaction.source_id].append((rel, interaction.target_id, conf, True))
        # Reverse edge (target -> source): a real forward step only if symmetric;
        # otherwise stored for undirected neighbour queries but marked reverse.
        self._edges[interaction.target_id].append((rel, interaction.source_id, conf, symmetric))

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
        for rel, neighbor_id, _conf, _forward in self._edges.get(entity_id, []):
            if relation is not None and rel != relation:
                continue
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
        for rel, neighbor_id, conf, forward in self._edges.get(entity_id, []):
            if relation is not None and rel != relation:
                continue
            if direction == "forward" and not forward:
                continue
            if neighbor_id not in self._entities:
                continue
            out.append(Edge(relation=rel, target_id=neighbor_id, confidence=conf, forward=forward))
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
