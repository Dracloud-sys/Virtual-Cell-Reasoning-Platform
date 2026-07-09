"""Tests for the cell-engineering vertical ontology (v0): 5 nodes + relations."""

from __future__ import annotations

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.persistence import load_store, save_store
from virtualcell.knowledge.schema import (
    AssayResult,
    CellLine,
    EntityType,
    Interaction,
    Marker,
    Mechanism,
    Phenotype,
    RelationType,
)
from virtualcell.reasoning.explain import explain


def _immortalization_ish() -> InMemoryKnowledgeStore:
    """A tiny 5-node/relation graph, per the Phase-1 success criterion."""
    store = InMemoryKnowledgeStore()
    store.upsert(
        CellLine(id="cell:iBSC-01", name="iBSC-01", species="bovine", cell_type="fibroblast")
    )
    store.upsert(
        AssayResult(id="assay:PDL", name="PDL increasing", assay="PDL", direction="increasing")
    )
    store.upsert(Phenotype(id="phenotype:sustained_proliferation", name="Sustained proliferation"))
    store.upsert(Marker(id="marker:TERT", name="TERT", modality="molecular"))
    store.upsert(Mechanism(id="mechanism:telomere_maintenance", name="Telomere maintenance"))

    store.add_interaction(
        Interaction(
            source_id="cell:iBSC-01", target_id="assay:PDL", relation=RelationType.HAS_RESULT
        )
    )
    store.add_interaction(
        Interaction(
            source_id="assay:PDL",
            target_id="phenotype:sustained_proliferation",
            relation=RelationType.INDICATES,
        )
    )
    store.add_interaction(
        Interaction(
            source_id="marker:TERT",
            target_id="mechanism:telomere_maintenance",
            relation=RelationType.ASSOCIATED_WITH,
        )
    )
    return store


def test_subclasses_set_type_and_fields() -> None:
    cell = CellLine(id="cell:x", name="X", species="bovine", cell_type="preadipocyte")
    assay = AssayResult(
        id="a:x", name="A", assay="qPCR", value="1.8", unit="fold_change", direction="up"
    )
    assert cell.type == EntityType.CELL_LINE
    assert (cell.species, cell.cell_type) == ("bovine", "preadipocyte")
    assert assay.type == EntityType.ASSAY_RESULT
    assert assay.direction == "up" and assay.unit == "fold_change"
    assert Phenotype(id="p:x", name="P").type == EntityType.PHENOTYPE
    assert Mechanism(id="m:x", name="M").type == EntityType.MECHANISM
    assert Marker(id="mk:x", name="MK").type == EntityType.MARKER


def test_associated_with_is_symmetric_but_indicates_is_directed() -> None:
    store = _immortalization_ish()

    # ASSOCIATED_WITH is symmetric: both directions are forward.
    fwd_marker = {e.target_id for e in store.edges("marker:TERT")}
    fwd_mech = {e.target_id for e in store.edges("mechanism:telomere_maintenance")}
    assert "mechanism:telomere_maintenance" in fwd_marker
    assert "marker:TERT" in fwd_mech

    # INDICATES is directed: forward only from the assay result to the phenotype.
    fwd_assay = {e.target_id for e in store.edges("assay:PDL")}
    fwd_pheno = {e.target_id for e in store.edges("phenotype:sustained_proliferation")}
    assert "phenotype:sustained_proliferation" in fwd_assay
    assert "assay:PDL" not in fwd_pheno
    assert "assay:PDL" in {
        e.target_id for e in store.edges("phenotype:sustained_proliferation", direction="any")
    }


def test_explain_reasons_over_ontology_nodes() -> None:
    store = _immortalization_ish()
    links = {link.target_id: link for link in explain(store, "cell:iBSC-01", max_hops=2).links}
    # CellLine -> assay result (1-hop) -> phenotype (2-hop inference, downgraded).
    assert links["assay:PDL"].hops == 1
    assert links["phenotype:sustained_proliferation"].hops == 2


def test_persistence_preserves_new_node_types(tmp_path) -> None:
    store = _immortalization_ish()
    path = tmp_path / "onto.json"
    save_store(store, path)
    loaded = load_store(path)

    assay = loaded.get("assay:PDL")
    assert assay.type == EntityType.ASSAY_RESULT
    assert assay.assay == "PDL" and assay.direction == "increasing"  # subclass fields survive
    assert loaded.get("cell:iBSC-01").species == "bovine"
