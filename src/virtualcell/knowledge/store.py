"""The KnowledgeStore protocol.

Any backend (in-memory, Neo4j, Qdrant, ...) implements this interface, so the rest
of the platform is agnostic to storage. Backends are selected by configuration.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from virtualcell.knowledge.schema import BioEntity, Interaction


class Edge(BaseModel):
    """A typed, weighted, directed connection from one entity to a neighbour.

    Unlike :meth:`KnowledgeStore.neighbors` (which returns only entities), an edge
    preserves the relation type, confidence, and direction needed for mechanistic
    traversal. ``forward`` is ``True`` when traversing the edge follows its
    biological arrow (or the relation is symmetric); a reverse edge of a directed
    relation has ``forward=False`` and should not be treated as a causal step.
    """

    relation: str
    target_id: str
    confidence: float = 1.0
    forward: bool = True


@runtime_checkable
class KnowledgeStore(Protocol):
    """Storage-agnostic interface over the biological knowledge graph."""

    def upsert(self, entity: BioEntity) -> None:
        """Insert or update an entity."""
        ...

    def add_interaction(self, interaction: Interaction) -> None:
        """Add a typed edge between two existing entities."""
        ...

    def get(self, entity_id: str) -> BioEntity | None:
        """Fetch an entity by id, or None."""
        ...

    def neighbors(self, entity_id: str, relation: str | None = None) -> list[BioEntity]:
        """Return entities directly connected to ``entity_id``.

        If ``relation`` is given, restrict to edges of that relation type.
        """
        ...

    def edges(
        self, entity_id: str, relation: str | None = None, direction: str = "forward"
    ) -> list[Edge]:
        """Return typed, weighted, directed edges outgoing from ``entity_id``.

        ``direction`` is ``"forward"`` (default; only edges whose arrow points away
        from ``entity_id``, plus symmetric relations) or ``"any"`` (all edges,
        including reverse edges of directed relations). If ``relation`` is given,
        restrict to that relation type.
        """
        ...

    def search(self, query: str, k: int = 10) -> list[BioEntity]:
        """Return up to ``k`` entities matching ``query`` (name/alias/description)."""
        ...


def get_store(backend: str | None = None) -> KnowledgeStore:
    """Factory: return a KnowledgeStore for the configured backend.

    Defaults to the in-memory backend, which has no external dependencies.
    """
    from virtualcell.core.config import get_settings

    backend = backend or get_settings().knowledge_backend

    if backend == "memory":
        from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore

        return InMemoryKnowledgeStore()
    if backend == "neo4j":
        from virtualcell.knowledge.backends.neo4j import Neo4jKnowledgeStore

        return Neo4jKnowledgeStore()

    raise ValueError(f"unknown knowledge backend: {backend}")
