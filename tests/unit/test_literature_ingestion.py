"""Tests for reviewed ingestion of canonical literature evidence (PR8e)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import EntityType, RelationType
from virtualcell.literature.canonical import experiment_runs_from_verified
from virtualcell.literature.documents import parse_jats
from virtualcell.literature.extraction import ExtractionTask, extract_deterministic
from virtualcell.literature.ingestion import (
    EVIDENCE_KIND,
    INGESTION_SOURCE,
    LITERATURE_EVIDENCE_CONFIDENCE,
    REVIEW_STATUS,
    ingest_runs,
)
from virtualcell.literature.verification import verify_candidates

_CLOCK = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def document(jats_xml, article_identifier):
    return parse_jats(jats_xml, article=article_identifier, provider="europe_pmc")


def _runs(document, targets):
    task = ExtractionTask(target_measurements=list(targets))
    result = extract_deterministic(document, task)
    decisions = verify_candidates(document, result, task, verified_at=_CLOCK)
    return experiment_runs_from_verified(result.measurements, decisions)


def _table_doc(article, table_html: str):
    return parse_jats(
        f'<article><back><table-wrap id="T1"><table>{table_html}</table>'
        "</table-wrap></back></article>",
        article=article,
    )


# --- what gets written -------------------------------------------------------


def test_ingest_creates_marker_assay_and_weak_edge(document) -> None:
    store = InMemoryKnowledgeStore()
    runs = _runs(document, ["TERT"])  # TERT/P3 and TERT/P35
    report = ingest_runs(store, runs)

    assert report.runs_ingested == 2
    assert report.markers == ["lit:marker:tert"]  # one shared marker
    assert len(report.assay_results) == 2  # one per measurement
    assert report.interactions_added == 2

    marker = store.get("lit:marker:tert")
    assert marker is not None and marker.type is EntityType.MARKER
    assays = [e for e in store.all_entities() if e.type is EntityType.ASSAY_RESULT]
    assert len(assays) == 2


def test_only_weak_associated_with_edges_are_created(document) -> None:
    store = InMemoryKnowledgeStore()
    ingest_runs(store, _runs(document, ["TERT", "CDK4"]))
    interactions = store.all_interactions()
    assert interactions
    assert all(i.relation is RelationType.ASSOCIATED_WITH for i in interactions)
    # Never a strong/causal relation.
    strong = {
        RelationType.PROMOTES,
        RelationType.INHIBITS,
        RelationType.REGULATES,
        RelationType.ENCODES,
        RelationType.HAS_RESULT,
        RelationType.INDICATES,
    }
    assert all(i.relation not in strong for i in interactions)


def test_edge_confidence_is_the_conservative_fixed_weight(document) -> None:
    store = InMemoryKnowledgeStore()
    ingest_runs(store, _runs(document, ["TERT"]))
    assert all(i.confidence == LITERATURE_EVIDENCE_CONFIDENCE for i in store.all_interactions())


# --- provenance & review flagging --------------------------------------------


def test_nodes_are_namespaced_and_flagged_for_review(document) -> None:
    store = InMemoryKnowledgeStore()
    ingest_runs(store, _runs(document, ["TERT"]))
    for entity in store.all_entities():
        assert entity.id.startswith("lit:")  # never merged into curated ids
        assert entity.properties["review_status"] == REVIEW_STATUS
        assert entity.properties["source"] == INGESTION_SOURCE


def test_assay_node_carries_full_source_provenance(document) -> None:
    store = InMemoryKnowledgeStore()
    ingest_runs(store, _runs(document, ["TERT"]))
    assay = next(e for e in store.all_entities() if e.type is EntityType.ASSAY_RESULT)
    props = assay.properties
    assert props["evidence_kind"] == EVIDENCE_KIND
    assert props["article_pmcid"] == "PMC1" and props["article_pmid"] == "1"
    assert props["source_kind"] == "table" and props["table_id"] == "T1"
    assert props["source_text_hash"] and props["candidate_id"]
    assert props["verification_status"] == "machine_verified"
    assert props["verified_at"] == _CLOCK.isoformat()
    assert props["run_id"].startswith("literature:")


def test_edge_evidence_records_provenance_and_review_status(document) -> None:
    store = InMemoryKnowledgeStore()
    ingest_runs(store, _runs(document, ["TERT"]))
    evidence = store.all_interactions()[0].evidence
    assert any(e == f"review_status:{REVIEW_STATUS}" for e in evidence)
    assert any(e.startswith("run:literature:") for e in evidence)
    assert any(e.startswith("source_hash:") for e in evidence)
    assert any(e.startswith("verified:") for e in evidence)


def test_value_and_unit_and_comparator_are_preserved(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>P35</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>&lt;0.05</td></tr></tbody>",
    )
    store = InMemoryKnowledgeStore()
    ingest_runs(store, _runs(doc, ["TERT"]))
    assay = next(e for e in store.all_entities() if e.type is EntityType.ASSAY_RESULT)
    assert assay.value == "0.05"
    assert assay.properties["comparator"] == "<"  # a bound is not lost
    assert assay.properties["raw_value"] == "<0.05"


# --- determinism, idempotency, purity ----------------------------------------


def test_ingestion_is_idempotent(document) -> None:
    store = InMemoryKnowledgeStore()
    runs = _runs(document, ["TERT", "CDK4"])
    first = ingest_runs(store, runs)
    entities_after_first = {e.id for e in store.all_entities()}
    interactions_after_first = len(store.all_interactions())

    second = ingest_runs(store, runs)  # re-ingest the exact same runs
    assert second.interactions_added == 0
    assert {e.id for e in store.all_entities()} == entities_after_first
    assert len(store.all_interactions()) == interactions_after_first
    assert first.markers == second.markers  # deterministic ids


def test_measurements_of_the_same_target_share_one_marker(document) -> None:
    store = InMemoryKnowledgeStore()
    ingest_runs(store, _runs(document, ["TERT"]))  # two TERT measurements
    markers = [e for e in store.all_entities() if e.type is EntityType.MARKER]
    assert len(markers) == 1  # one marker node, two assay results linked to it
    linked = store.neighbors("lit:marker:tert")
    assert len(linked) == 2


def test_empty_runs_leave_the_store_untouched(document) -> None:
    store = InMemoryKnowledgeStore()
    report = ingest_runs(store, [])
    assert report.runs_ingested == 0
    assert store.all_entities() == [] and store.all_interactions() == []


def test_run_without_a_measurement_is_skipped(document) -> None:
    from virtualcell.core.experiment import (
        AcquisitionMode,
        ExperimentRun,
        OriginKind,
        Provenance,
    )

    empty_run = ExperimentRun(
        run_id="literature:empty",
        provenance=Provenance(
            origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.IMPORTED
        ),
    )
    store = InMemoryKnowledgeStore()
    report = ingest_runs(store, [empty_run])
    assert report.runs_ingested == 0
    assert any("no measurement" in s for s in report.skipped)
    assert store.all_entities() == []
