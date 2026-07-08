"""The DataSource protocol for ingesting external biological datasets.

Each connector (Gene Ontology, Reactome, UniProt, ...) yields entities and
interactions that are loaded into a KnowledgeStore. Connectors are the seam through
which heterogeneous omics data enters the platform.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from virtualcell.knowledge.schema import BioEntity, Interaction
from virtualcell.knowledge.store import KnowledgeStore


@runtime_checkable
class DataSource(Protocol):
    """A connector that produces entities and interactions from an external source."""

    name: str

    def entities(self) -> Iterator[BioEntity]:
        """Yield entities from the source."""
        ...

    def interactions(self) -> Iterator[Interaction]:
        """Yield interactions from the source."""
        ...


def load_into(source: DataSource, store: KnowledgeStore) -> tuple[int, int]:
    """Load all entities then interactions from ``source`` into ``store``.

    Returns a ``(n_entities, n_interactions)`` count of what was added. Entities are
    loaded first so interaction endpoints resolve. Interactions whose endpoints are
    absent from the graph are skipped (not counted) rather than raising — this lets
    edge-only sources (e.g. protein–protein interactions) be merged onto a graph
    that already holds the referenced proteins.
    """
    n_entities = 0
    for entity in source.entities():
        store.upsert(entity)
        n_entities += 1

    n_interactions = 0
    for interaction in source.interactions():
        try:
            store.add_interaction(interaction)
        except KeyError:
            continue  # endpoint not present in this graph; skip the edge
        n_interactions += 1

    return n_entities, n_interactions
