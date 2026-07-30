"""Tests for resolving literature markers onto curated ontology nodes (PR9-c)."""

from __future__ import annotations

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Gene, Marker
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.literature.resolution import (
    RESOLUTION_CONFIDENCE,
    RESOLUTION_RELATION,
    resolve_literature_markers,
)


@pytest.fixture
def store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    source = ImmortalizationSeedSource()
    for entity in source.entities():
        store.upsert(entity)
    for interaction in source.interactions():
        store.add_interaction(interaction)
    return store


def _lit_marker(store, name: str) -> str:
    marker_id = f"lit:marker:{name.lower()}"
    store.upsert(Marker(id=marker_id, name=name, properties={"source": "literature_ingestion"}))
    return marker_id


# --- resolution --------------------------------------------------------------


def test_exact_name_resolves_to_curated_gene(store) -> None:
    marker_id = _lit_marker(store, "TERT")
    report = resolve_literature_markers(store, [marker_id])
    assert report.resolved == [(marker_id, "gene:TERT")]
    assert report.edges_added == 1


def test_alias_resolves_to_curated_gene(store) -> None:
    # "p16" is an alias of the curated CDKN2A gene.
    marker_id = _lit_marker(store, "p16")
    report = resolve_literature_markers(store, [marker_id])
    assert report.resolved == [(marker_id, "gene:CDKN2A")]


def test_resolution_edge_is_weak_and_reviewable(store) -> None:
    marker_id = _lit_marker(store, "TERT")
    resolve_literature_markers(store, [marker_id])
    edges = [e for e in store.edges(marker_id, direction="any") if e.target_id == "gene:TERT"]
    assert edges and edges[0].relation == RESOLUTION_RELATION.value
    assert edges[0].confidence == RESOLUTION_CONFIDENCE  # weak, fixed
    interaction = next(
        i
        for i in store.all_interactions()
        if i.source_id == marker_id and i.target_id == "gene:TERT"
    )
    assert any("review_status:pending_review" in e for e in interaction.evidence)


def test_curated_node_becomes_reachable_to_the_marker(store) -> None:
    marker_id = _lit_marker(store, "TERT")
    resolve_literature_markers(store, [marker_id])
    # ASSOCIATED_WITH is symmetric, so the curated gene now reaches the literature marker.
    assert marker_id in {n.id for n in store.neighbors("gene:TERT")}


def test_nodes_are_linked_not_merged(store) -> None:
    marker_id = _lit_marker(store, "TERT")
    resolve_literature_markers(store, [marker_id])
    # Both nodes still exist independently; resolution adds an edge, never a merge.
    assert store.get(marker_id) is not None and store.get("gene:TERT") is not None


def test_resolution_is_idempotent(store) -> None:
    marker_id = _lit_marker(store, "TERT")
    first = resolve_literature_markers(store, [marker_id])
    interactions_after_first = len(store.all_interactions())
    second = resolve_literature_markers(store, [marker_id])
    assert first.resolved == second.resolved
    assert second.edges_added == 0
    assert len(store.all_interactions()) == interactions_after_first


def test_unmatched_marker_is_left_unresolved(store) -> None:
    marker_id = _lit_marker(store, "NOSUCHGENE9")
    report = resolve_literature_markers(store, [marker_id])
    assert report.unresolved == [marker_id]
    assert report.resolved == [] and report.edges_added == 0


def test_ambiguous_match_is_skipped_not_guessed() -> None:
    store = InMemoryKnowledgeStore()
    # Two curated nodes that both normalize to the same name.
    store.upsert(Gene(id="gene:DUP", name="DUP", symbol="DUP"))
    store.upsert(Marker(id="marker:dup", name="DUP"))
    marker_id = _lit_marker(store, "DUP")
    report = resolve_literature_markers(store, [marker_id])
    assert report.ambiguous == [marker_id]
    assert report.resolved == [] and report.edges_added == 0


def test_no_synonym_or_fuzzy_resolution(store) -> None:
    # "telomerase" is TERT's biology but not its name/symbol/alias -> not resolved.
    marker_id = _lit_marker(store, "telomerase")
    report = resolve_literature_markers(store, [marker_id])
    assert marker_id in report.unresolved
