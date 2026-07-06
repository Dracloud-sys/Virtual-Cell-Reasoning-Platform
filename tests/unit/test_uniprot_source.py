"""Tests for the UniProtKB connector, including cross-source enrichment."""

from __future__ import annotations

from pathlib import Path

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import EntityType, RelationType
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.reactome import ReactomeSource
from virtualcell.knowledge.sources.uniprot import UniProtSource

FIXTURES = Path(__file__).parent.parent / "fixtures"
UNIPROT_FIXTURE = FIXTURES / "uniprot_sample.tsv"
REACTOME_FIXTURE = FIXTURES / "reactome_uniprot2reactome_sample.txt"


def test_header_skipped_and_proteins_genes_extracted() -> None:
    entities = list(UniProtSource(path=str(UNIPROT_FIXTURE)).entities())
    proteins = [e for e in entities if e.type == EntityType.PROTEIN]
    genes = [e for e in entities if e.type == EntityType.GENE]

    # 5 protein rows (header skipped, BROKEN line dropped); 4 have a primary gene.
    assert len(proteins) == 5
    assert len(genes) == 4
    assert all(e.id != "protein:Entry" for e in proteins)  # header not ingested

    p53 = next(e for e in proteins if e.id == "protein:P04637")
    assert p53.name == "Cellular tumor antigen p53"
    assert "TP53" in p53.aliases
    assert all(e.properties.get("source") == "uniprot" for e in entities)


def test_encodes_interactions() -> None:
    inter = list(UniProtSource(path=str(UNIPROT_FIXTURE)).interactions())
    assert len(inter) == 4
    assert all(i.relation == RelationType.ENCODES for i in inter)
    assert all(i.source_id.startswith("gene:") for i in inter)
    assert all(i.target_id.startswith("protein:") for i in inter)


def test_protein_without_gene_yields_no_edge() -> None:
    # P0DTD1 (SARS-CoV-2 polyprotein) has an empty gene column.
    entities = list(UniProtSource(path=str(UNIPROT_FIXTURE)).entities())
    assert any(e.id == "protein:P0DTD1" for e in entities)
    inter = list(UniProtSource(path=str(UNIPROT_FIXTURE)).interactions())
    assert all(i.target_id != "protein:P0DTD1" for i in inter)


def test_species_filter_excludes_other_organisms() -> None:
    entities = list(UniProtSource(path=str(UNIPROT_FIXTURE), species="Homo sapiens").entities())
    proteins = [e for e in entities if e.type == EntityType.PROTEIN]
    assert len(proteins) == 4  # the SARS-CoV-2 protein is excluded
    assert all("P0DTD1" not in e.id for e in proteins)


def test_load_into_store() -> None:
    store = InMemoryKnowledgeStore()
    n_entities, n_interactions = load_into(UniProtSource(path=str(UNIPROT_FIXTURE)), store)
    assert (n_entities, n_interactions) == (9, 4)
    neighbors = store.neighbors("gene:TP53")
    assert any(n.id == "protein:P04637" for n in neighbors)


def test_uniprot_enriches_reactome_protein() -> None:
    """Reactome yields a skeletal protein; UniProt upserts a rich record over it."""
    store = InMemoryKnowledgeStore()
    load_into(ReactomeSource(path=str(REACTOME_FIXTURE)), store)
    # After Reactome only, the protein name is just its accession.
    assert store.get("protein:P04637").name == "P04637"

    load_into(UniProtSource(path=str(UNIPROT_FIXTURE)), store)
    # UniProt enriches the same protein:P04637 node in place.
    enriched = store.get("protein:P04637")
    assert enriched.name == "Cellular tumor antigen p53"
    # ...and the protein now links to both its gene (UniProt) and pathways (Reactome).
    neighbor_ids = {n.id for n in store.neighbors("protein:P04637")}
    assert "gene:TP53" in neighbor_ids
    assert any(nid.startswith("pathway:") for nid in neighbor_ids)


def test_missing_path_raises() -> None:
    with pytest.raises(ValueError, match="requires a path"):
        list(UniProtSource().entities())
