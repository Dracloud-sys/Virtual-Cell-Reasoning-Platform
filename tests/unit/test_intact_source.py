"""Tests for the IntAct protein-protein interaction connector."""

from __future__ import annotations

from pathlib import Path

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Protein, RelationType
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.intact import IntActSource
from virtualcell.knowledge.sources.sample import SampleDataSource
from virtualcell.reasoning.explain import explain

FIXTURE = Path(__file__).parent.parent / "fixtures" / "intact_sample.txt"


def _proteins(*accessions: str) -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for acc in accessions:
        store.upsert(Protein(id=f"protein:{acc}", name=acc))
    return store


def test_parses_valid_pairs_skipping_self_and_non_uniprot() -> None:
    store = _proteins("P04637", "Q00987", "P38398")
    _, n_interactions = load_into(IntActSource(path=str(FIXTURE)), store)
    # 3 valid pairs; the chebi row and the P04637-P04637 self-interaction are skipped.
    assert n_interactions == 3
    # Isoform P38398-1 is collapsed to the canonical accession, so the edge lands.
    neigh = {e.id for e in store.neighbors("protein:P38398")}
    assert "protein:P04637" in neigh


def test_edges_are_symmetric_interactions_with_score() -> None:
    inter = list(IntActSource(path=str(FIXTURE)).interactions())
    assert all(i.relation == RelationType.INTERACTS_WITH for i in inter)
    assert all(i.evidence == ["intact"] for i in inter)
    p53_mdm2 = next(
        i for i in inter if {i.source_id, i.target_id} == {"protein:P04637", "protein:Q00987"}
    )
    assert p53_mdm2.confidence == pytest.approx(0.99)


def test_min_score_filters_weak_interactions() -> None:
    store = _proteins("P04637", "Q00987", "P38398")
    _, n = load_into(IntActSource(path=str(FIXTURE), min_score=0.5), store)
    assert n == 2  # the 0.10 Q00987-P38398 edge is filtered out


def test_missing_endpoints_are_skipped_by_load() -> None:
    # P38398 is absent, so its edges are skipped rather than raising.
    store = _proteins("P04637", "Q00987")
    _, n = load_into(IntActSource(path=str(FIXTURE)), store)
    assert n == 1  # only P04637-Q00987 survives


def test_ppi_extends_mechanistic_reach() -> None:
    # Sample graph alone: TP53's forward reach excludes MDM2 (it is an upstream
    # regulator). Adding the physical p53-MDM2 interaction makes it reachable.
    store = InMemoryKnowledgeStore()
    load_into(SampleDataSource(), store)
    before = {link.target_id for link in explain(store, "gene:TP53", max_hops=2).links}
    assert "protein:Q00987" not in before

    load_into(IntActSource(path=str(FIXTURE)), store)
    after = {link.target_id for link in explain(store, "gene:TP53", max_hops=2).links}
    assert "protein:Q00987" in after


def test_missing_path_raises() -> None:
    with pytest.raises(ValueError, match="requires a path"):
        list(IntActSource().interactions())
