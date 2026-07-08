"""JSON snapshot persistence for the in-memory knowledge graph.

An ingested graph lives only in memory, so it vanishes when the process exits.
:func:`save_store` writes it to a portable JSON file (entities + original
interactions) and :func:`load_store` rebuilds an :class:`InMemoryKnowledgeStore`
from it — the lightweight alternative to a database, and the prerequisite for
querying real ingested data across sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import (
    BioEntity,
    EntityType,
    Gene,
    Interaction,
    Pathway,
    Protein,
)

_SCHEMA_VERSION = 1

# Reconstruct the concrete entity subclass so type-specific fields survive a round trip.
_ENTITY_CLASSES: dict[EntityType, type[BioEntity]] = {
    EntityType.GENE: Gene,
    EntityType.PROTEIN: Protein,
    EntityType.PATHWAY: Pathway,
}


def _entity_from_dict(data: dict) -> BioEntity:
    cls = _ENTITY_CLASSES.get(EntityType(data["type"]), BioEntity)
    return cls(**data)


def save_store(store: InMemoryKnowledgeStore, path: str | Path) -> tuple[int, int]:
    """Write ``store`` to ``path`` as JSON. Returns ``(n_entities, n_interactions)``."""
    entities = store.all_entities()
    interactions = store.all_interactions()
    payload = {
        "version": _SCHEMA_VERSION,
        "entities": [e.model_dump() for e in entities],
        "interactions": [i.model_dump() for i in interactions],
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")
    return len(entities), len(interactions)


def load_store(path: str | Path) -> InMemoryKnowledgeStore:
    """Rebuild an :class:`InMemoryKnowledgeStore` from a JSON snapshot."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = data.get("version")
    if version != _SCHEMA_VERSION:
        raise ValueError(f"unsupported snapshot version: {version!r} (expected {_SCHEMA_VERSION})")

    store = InMemoryKnowledgeStore()
    for entity_data in data.get("entities", []):
        store.upsert(_entity_from_dict(entity_data))
    for interaction_data in data.get("interactions", []):
        store.add_interaction(Interaction(**interaction_data))
    return store
