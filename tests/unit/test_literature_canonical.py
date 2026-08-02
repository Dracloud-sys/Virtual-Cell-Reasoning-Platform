"""Tests for canonical conversion of verified literature measurements (PR8d-2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from virtualcell.core.experiment import (
    AcquisitionMode,
    ExperimentRun,
    OriginKind,
)
from virtualcell.literature.canonical import (
    RUN_NAMESPACE,
    SOURCE_SYSTEM,
    experiment_runs_from_verified,
)
from virtualcell.literature.contracts import (
    CandidateKind,
    ExtractedMeasurementCandidate,
    ExtractionMethod,
    ParseStatus,
    SourceKind,
    SourceLocator,
    VerificationDecision,
    VerificationStatus,
)
from virtualcell.literature.documents import parse_jats
from virtualcell.literature.extraction import (
    ExtractionTask,
    extract_deterministic,
)
from virtualcell.literature.verification import METHOD, VERIFIER, verify_candidates

_CLOCK = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def document(jats_xml, article_identifier):
    return parse_jats(jats_xml, article=article_identifier, provider="europe_pmc")


def _table_doc(article, table_html: str):
    return parse_jats(
        f'<article><back><table-wrap id="T1"><table>{table_html}</table>'
        "</table-wrap></back></article>",
        article=article,
    )


def _verified(document, targets):
    """Extract + verify against a document; returns (measurements, decisions)."""
    task = ExtractionTask(target_measurements=list(targets))
    result = extract_deterministic(document, task)
    decisions = verify_candidates(document, result, task, verified_at=_CLOCK)
    return result.measurements, decisions


def _decision(candidate, status, kind=CandidateKind.MEASUREMENT):
    return VerificationDecision(
        candidate_id=candidate.candidate_id,
        candidate_kind=kind,
        status=status,
        verifier=VERIFIER,
        method=METHOD,
        verified_at=_CLOCK,
        source_text_hash=candidate.source_locator.source_text_hash,
    )


# --- only machine-verified measurements convert ------------------------------


def test_machine_verified_measurement_becomes_one_run(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    runs = experiment_runs_from_verified(measurements, decisions)
    assert len(runs) == len(measurements) == 2  # TERT/P3 and TERT/P35
    tert_p35 = next(r for r in runs if r.observations[0].measurements[0].value == 2.4)
    m = tert_p35.observations[0].measurements[0]
    assert m.name == "TERT" and m.value == 2.4
    assert tert_p35.provenance.origin_kind is OriginKind.EXPERIMENT
    assert tert_p35.provenance.acquisition_mode is AcquisitionMode.IMPORTED
    assert tert_p35.provenance.source_system == SOURCE_SYSTEM


def test_pending_review_measurement_is_not_converted(document) -> None:
    # A qualitative table cell verifies as PENDING_REVIEW -> never a run.
    measurements, decisions = _verified(document, ["SA_b_gal"])
    assert all(d.status is VerificationStatus.PENDING_REVIEW for d in decisions)
    assert experiment_runs_from_verified(measurements, decisions) == []


def test_rejected_measurement_is_not_converted(document) -> None:
    measurements, _ = _verified(document, ["TERT"])
    rejected = [_decision(m, VerificationStatus.REJECTED) for m in measurements]
    assert experiment_runs_from_verified(measurements, rejected) == []


def test_claim_kind_decision_is_never_converted(document) -> None:
    # Even a (nonsensical) MACHINE_VERIFIED decision tagged as a CLAIM must not convert
    # a measurement candidate: only MEASUREMENT-kind machine-verified decisions do.
    measurements, _ = _verified(document, ["TERT"])
    claimish = [
        _decision(m, VerificationStatus.MACHINE_VERIFIED, kind=CandidateKind.CLAIM)
        for m in measurements
    ]
    assert experiment_runs_from_verified(measurements, claimish) == []


def test_statistic_measurement_is_never_converted(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>P value</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>0.03</td></tr></tbody>",
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["P value"]))
    statistic = result.measurements[0]
    assert statistic.statistic == "p_value"
    # Force a (defensively guarded-against) machine-verified decision for the statistic.
    forced = [_decision(statistic, VerificationStatus.MACHINE_VERIFIED)]
    assert experiment_runs_from_verified([statistic], forced) == []


def test_dangling_decision_without_its_candidate_converts_nothing(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    # Decisions but no measurements to link them to.
    assert experiment_runs_from_verified([], decisions) == []


# --- provenance & field mapping ----------------------------------------------


def test_provenance_carries_full_source_trail(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    run = experiment_runs_from_verified(measurements, decisions)[0]
    meta = run.provenance.metadata
    assert meta["article_pmcid"] == "PMC1" and meta["article_pmid"] == "1"
    assert meta["source_kind"] == "table" and meta["table_id"] == "T1"
    assert meta["source_text_hash"] and meta["candidate_id"]
    assert meta["verification_status"] == "machine_verified"
    assert meta["verifier"] == VERIFIER and meta["verification_method"] == METHOD
    assert meta["verified_at"] == _CLOCK.isoformat()
    assert run.provenance.source_run_id == document.article.stable_key()


def test_unit_is_mapped(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>P35</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>2.4-fold</td></tr></tbody>",
    )
    measurements, decisions = _verified(doc, ["TERT"])
    run = experiment_runs_from_verified(measurements, decisions)[0]
    m = run.observations[0].measurements[0]
    assert m.value == 2.4 and m.unit == "fold"


def test_comparator_bound_is_preserved_as_a_flag(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>P35</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>&lt;0.05</td></tr></tbody>",
    )
    measurements, decisions = _verified(doc, ["TERT"])
    run = experiment_runs_from_verified(measurements, decisions)[0]
    m = run.observations[0].measurements[0]
    assert m.value == 0.05
    assert "bound:<" in m.quality_flags  # a bound is not read as a point estimate
    assert run.provenance.metadata["comparator"] == "<"


def test_uncertainty_is_preserved(document) -> None:
    measurements, decisions = _verified(document, ["CDK4"])
    run = next(
        r
        for r in experiment_runs_from_verified(measurements, decisions)
        if r.observations[0].measurements[0].value == 1.1
    )
    m = run.observations[0].measurements[0]
    assert "uncertainty:0.2" in m.quality_flags
    assert run.provenance.metadata["uncertainty"] == 0.2


def test_conditions_are_copied_verbatim(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    run = next(
        r
        for r in experiment_runs_from_verified(measurements, decisions)
        if r.observations[0].measurements[0].value == 2.4
    )
    assert run.conditions["sample_group"] == "P35"
    assert run.observations[0].conditions["sample_group"] == "P35"


def test_passage_time_point_is_parsed_when_present(article_identifier) -> None:
    cand = ExtractedMeasurementCandidate(
        measurement_name="TERT",
        time_point="passage 35",
        raw_value="2.4",
        parsed_value=2.4,
        parse_status=ParseStatus.PARSED,
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=article_identifier,
            source_kind=SourceKind.TABLE,
            table_id="T1",
            row_index=0,
            column_index=2,
            row_label="TERT",
            column_label="P35",
            source_text="2.4",
        ),
    )
    run = experiment_runs_from_verified(
        [cand], [_decision(cand, VerificationStatus.MACHINE_VERIFIED)]
    )[0]
    tp = run.observations[0].time_point
    assert tp.kind == "passage" and tp.value == 35


def test_missing_time_point_falls_back_to_a_timestamp(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])  # time_point is None
    run = experiment_runs_from_verified(measurements, decisions)[0]
    tp = run.observations[0].time_point
    assert tp.kind == "timestamp" and tp.value == _CLOCK


# --- determinism & purity ----------------------------------------------------


def test_run_ids_are_deterministic_and_prefixed(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    first = experiment_runs_from_verified(measurements, decisions)
    second = experiment_runs_from_verified(measurements, decisions)
    assert [r.run_id for r in first] == [r.run_id for r in second]
    assert all(r.run_id.startswith(f"{RUN_NAMESPACE}:") for r in first)


def test_duplicate_input_collapses_to_one_run(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    runs = experiment_runs_from_verified(measurements + measurements, decisions)
    assert len(runs) == len(measurements)  # duplicates do not fork a run


def test_runs_round_trip_through_json(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    for run in experiment_runs_from_verified(measurements, decisions):
        assert ExperimentRun.model_validate(run.model_dump(mode="json"))


def test_input_candidates_are_not_mutated(document) -> None:
    measurements, decisions = _verified(document, ["TERT"])
    before = [m.model_dump() for m in measurements]
    experiment_runs_from_verified(measurements, decisions)
    assert [m.model_dump() for m in measurements] == before
