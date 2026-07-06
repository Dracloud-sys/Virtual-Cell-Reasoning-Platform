"""Tests for the in-memory knowledge store and the sample data source."""

from __future__ import annotations

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import EntityType, Gene, Interaction, RelationType
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource


@pytest.fixture
def seeded_store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(SampleDataSource(), store)
    return store


def test_sample_loads(seeded_store: InMemoryKnowledgeStore) -> None:
    tp53 = seeded_store.get("gene:TP53")
    assert tp53 is not None
    assert tp53.type == EntityType.GENE
    assert tp53.symbol == "TP53"


def test_search_matches_alias(seeded_store: InMemoryKnowledgeStore) -> None:
    hits = seeded_store.search("p53")
    ids = {h.id for h in hits}
    assert "gene:TP53" in ids or "protein:P04637" in ids


def test_search_empty_query_returns_nothing(seeded_store: InMemoryKnowledgeStore) -> None:
    assert seeded_store.search("   ") == []


def test_neighbors_are_symmetric(seeded_store: InMemoryKnowledgeStore) -> None:
    # TP53 gene encodes the p53 protein; neighbor lookup should find it.
    neighbors = seeded_store.neighbors("gene:TP53")
    assert any(n.id == "protein:P04637" for n in neighbors)
    # and the reverse
    back = seeded_store.neighbors("protein:P04637")
    assert any(n.id == "gene:TP53" for n in back)


def test_neighbors_relation_filter(seeded_store: InMemoryKnowledgeStore) -> None:
    encoded = seeded_store.neighbors("gene:TP53", relation=RelationType.ENCODES.value)
    assert all(n.type == EntityType.PROTEIN for n in encoded)


def test_add_interaction_requires_existing_endpoints() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(Gene(id="gene:A", name="A"))
    with pytest.raises(KeyError):
        store.add_interaction(
            Interaction(source_id="gene:A", target_id="missing", relation=RelationType.ENCODES)
        )
