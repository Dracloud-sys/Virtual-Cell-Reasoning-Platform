"""The KnowledgeStore protocol.

Any backend (in-memory, Neo4j, Qdrant, ...) implements this interface, so the rest
of the platform is agnostic to storage. Backends are selected by configuration.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from virtualcell.knowledge.schema import BioEntity, Interaction


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
