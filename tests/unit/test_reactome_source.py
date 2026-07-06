"""Tests for the Reactome UniProt2Reactome connector."""

from __future__ import annotations

from pathlib import Path

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import EntityType, RelationType
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.reactome import ReactomeSource

FIXTURE = Path(__file__).parent.parent / "fixtures" / "reactome_uniprot2reactome_sample.txt"


def test_entities_are_deduplicated_and_species_filtered() -> None:
    src = ReactomeSource(path=str(FIXTURE))
    entities = list(src.entities())
    proteins = [e for e in entities if e.type == EntityType.PROTEIN]
    pathways = [e for e in entities if e.type == EntityType.PATHWAY]

    # 3 unique human proteins (P04637, Q00987, P38398), 3 unique human pathways.
    assert len(proteins) == 3
    assert len(pathways) == 3
    # The mouse row (R-MMU-69541) is filtered out by the default species filter.
    assert all("MMU" not in e.id for e in pathways)
    # Provenance is recorded on every entity.
    assert all(e.properties.get("source") == "reactome" for e in entities)


def test_interactions_are_participation_edges_with_evidence() -> None:
    inter = list(ReactomeSource(path=str(FIXTURE)).interactions())
    assert len(inter) == 5
    assert all(i.relation == RelationType.PARTICIPATES_IN for i in inter)
    assert all(i.source_id.startswith("protein:") for i in inter)
    assert all(i.target_id.startswith("pathway:") for i in inter)
    assert all(i.evidence for i in inter)


def test_load_into_store_populates_graph() -> None:
    store = InMemoryKnowledgeStore()
    n_entities, n_interactions = load_into(ReactomeSource(path=str(FIXTURE)), store)

    assert (n_entities, n_interactions) == (6, 5)
    # p53 (P04637) participates in two pathways in the fixture.
    neighbors = store.neighbors("protein:P04637")
    assert len(neighbors) == 2


def test_species_filter_can_select_other_organisms() -> None:
    entities = list(ReactomeSource(path=str(FIXTURE), species="Mus musculus").entities())
    # Only the single mouse row: one protein + one pathway.
    assert len(entities) == 2
    assert any("MMU" in e.id for e in entities)


def test_missing_path_raises() -> None:
    with pytest.raises(ValueError, match="requires a path"):
        list(ReactomeSource().entities())
