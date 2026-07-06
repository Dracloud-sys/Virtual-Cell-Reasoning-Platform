"""Cellular Knowledge Base (roadmap Stage 1).

The in-memory backend is fully working in v0.1; graph (Neo4j) and vector (Qdrant)
backends share the same :class:`KnowledgeStore` protocol.
"""

from __future__ import annotations

from virtualcell.knowledge.schema import (
    BioEntity,
    EntityType,
    Gene,
    Interaction,
    Pathway,
    Protein,
    RelationType,
)
from virtualcell.knowledge.store import KnowledgeStore, get_store

__all__ = [
    "BioEntity",
    "EntityType",
    "Gene",
    "Interaction",
    "KnowledgeStore",
    "Pathway",
    "Protein",
    "RelationType",
    "get_store",
]
