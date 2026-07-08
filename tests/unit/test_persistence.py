"""Tests for JSON snapshot persistence of the knowledge graph."""

from __future__ import annotations

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.persistence import load_store, save_store
from virtualcell.knowledge.schema import EntityType
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource
from virtualcell.reasoning.explain import explain


@pytest.fixture
def store() -> InMemoryKnowledgeStore:
    s = InMemoryKnowledgeStore()
    load_into(SampleDataSource(), s)
    return s


def test_round_trip_preserves_entities_and_subclass_fields(store, tmp_path) -> None:
    path = tmp_path / "graph.json"
    n_entities, n_interactions = save_store(store, path)
    assert (n_entities, n_interactions) == (5, 4)

    loaded = load_store(path)
    assert {e.id for e in loaded.all_entities()} == {e.id for e in store.all_entities()}

    # Subclass-specific fields survive (Gene.symbol here).
    tp53 = loaded.get("gene:TP53")
    assert tp53.type == EntityType.GENE
    assert tp53.symbol == "TP53"
    assert tp53.aliases  # list fields preserved


def test_round_trip_preserves_directed_edges_and_reasoning(store, tmp_path) -> None:
    path = tmp_path / "graph.json"
    save_store(store, path)
    loaded = load_store(path)

    # Reasoning behaves identically on the reloaded graph, including directionality.
    before = explain(store, "gene:TP53", max_hops=2)
    after = explain(loaded, "gene:TP53", max_hops=2)
    assert [(link.target_id, link.hops, link.tier) for link in before.links] == [
        (link.target_id, link.hops, link.tier) for link in after.links
    ]


def test_load_rejects_unknown_version(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"version": 999, "entities": [], "interactions": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported snapshot version"):
        load_store(path)
