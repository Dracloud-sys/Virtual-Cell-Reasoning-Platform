"""Canonical Experiment Schema v1 (PR12): versioning, compatibility, conformance.

The schema is the convergence point — literature evidence, domain packs and (from PR13)
raw-assay ingestion all produce or consume it — so these tests pin the version contract
itself and prove the *real* producers and consumers honour it.
"""

from __future__ import annotations

import pytest

from virtualcell.core.experiment import (
    SCHEMA_MAJOR,
    SCHEMA_VERSION,
    AcquisitionMode,
    ExperimentRun,
    Measurement,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    SchemaVersionError,
    is_compatible,
    parse_schema_version,
    validate_schema_version,
)


def _run(**over) -> ExperimentRun:
    fields = {
        "run_id": "run:1",
        "provenance": Provenance(
            origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.IMPORTED
        ),
        "observations": [
            Observation(
                time_point=PassageTimePoint(value=12),
                measurements=[Measurement(name="PDL", value=24.0)],
            )
        ],
    }
    fields.update(over)
    return ExperimentRun(**fields)


# --- the version contract -----------------------------------------------------


def test_runs_declare_the_schema_version_by_default() -> None:
    assert _run().schema_version == SCHEMA_VERSION
    assert SCHEMA_VERSION.startswith(f"{SCHEMA_MAJOR}.")


def test_schema_version_is_the_leading_serialized_key() -> None:
    # A reader should be able to see what it is looking at before interpreting anything.
    assert list(_run().model_dump(mode="json"))[0] == "schema_version"


def test_parse_schema_version_splits_major_and_minor() -> None:
    assert parse_schema_version("1.0") == (1, 0)
    assert parse_schema_version("2.17") == (2, 17)


@pytest.mark.parametrize("bad", ["", "1", "1.", ".1", "1.0.0", "v1.0", "one.zero", "1.x"])
def test_malformed_versions_are_rejected(bad: str) -> None:
    with pytest.raises(SchemaVersionError):
        parse_schema_version(bad)
    assert not is_compatible(bad)


def test_a_newer_minor_is_accepted() -> None:
    """Minors are additive, so the fields this reader knows are still present and
    correctly typed. Refusing structurally valid data would be the worse failure."""
    newer = f"{SCHEMA_MAJOR}.{999}"
    assert is_compatible(newer)
    validate_schema_version(newer)  # must not raise


def test_a_different_major_is_refused() -> None:
    # Silently reading a v2 payload as v1 would corrupt the meaning of the data.
    other = f"{SCHEMA_MAJOR + 1}.0"
    assert not is_compatible(other)
    with pytest.raises(SchemaVersionError, match="incompatible"):
        validate_schema_version(other)


def test_construction_rejects_a_malformed_version_but_allows_a_foreign_one() -> None:
    with pytest.raises(ValueError):
        _run(schema_version="not-a-version")
    # A run may legitimately be *built* for another reader; only the shape is enforced.
    foreign = _run(schema_version=f"{SCHEMA_MAJOR + 1}.0")
    assert not foreign.schema_is_compatible
    with pytest.raises(SchemaVersionError):
        foreign.require_compatible_schema()


def test_round_trip_preserves_the_version_and_content() -> None:
    original = _run()
    restored = ExperimentRun.model_validate(original.model_dump(mode="json"))
    assert restored == original
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.observations[0].measurements[0].value == 24.0


def test_a_stored_run_without_a_version_reads_as_current() -> None:
    """Runs serialized before PR12 carry no schema_version. They are v1-shaped, so they
    default rather than failing — the field was added additively."""
    payload = _run().model_dump(mode="json")
    del payload["schema_version"]
    assert ExperimentRun.model_validate(payload).schema_version == SCHEMA_VERSION


# --- real producers emit v1 ---------------------------------------------------


def test_literature_canonical_conversion_emits_v1(jats_xml, article_identifier) -> None:
    from datetime import UTC, datetime

    from virtualcell.literature.canonical import experiment_runs_from_verified
    from virtualcell.literature.documents import parse_jats
    from virtualcell.literature.extraction import ExtractionTask, extract_deterministic
    from virtualcell.literature.verification import verify_candidates

    document = parse_jats(jats_xml, article=article_identifier, provider="europe_pmc")
    task = ExtractionTask(target_measurements=["TERT"])
    result = extract_deterministic(document, task)
    decisions = verify_candidates(
        document, result, task, verified_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    )
    runs = experiment_runs_from_verified(result.measurements, decisions)

    assert runs
    assert all(run.schema_version == SCHEMA_VERSION for run in runs)
    assert all(run.schema_is_compatible for run in runs)


def test_immortalization_adapter_emits_v1() -> None:
    from virtualcell.agents.immortalization.adapters import passage_series_to_run
    from virtualcell.agents.immortalization.models import PassageObservation

    run = passage_series_to_run(
        [PassageObservation(passage=12, cumulative_PDL=24.0, DT_hours=40.0)],
        run_id="run:passages",
    )
    assert run.schema_version == SCHEMA_VERSION


# --- real consumers validate before trusting the shape ------------------------


def test_passage_extraction_refuses_an_incompatible_run() -> None:
    """The consumer reads field *meanings* out of a structure it did not build; an
    incompatible major could yield a plausible but wrong trajectory."""
    from virtualcell.agents.immortalization.adapters import run_to_passage_series

    foreign = _run(schema_version=f"{SCHEMA_MAJOR + 1}.0")
    with pytest.raises(SchemaVersionError):
        run_to_passage_series(foreign)


def test_passage_extraction_accepts_a_compatible_run() -> None:
    from virtualcell.agents.immortalization.adapters import (
        passage_series_to_run,
        run_to_passage_series,
    )
    from virtualcell.agents.immortalization.models import PassageObservation

    original = [PassageObservation(passage=12, cumulative_PDL=24.0, DT_hours=40.0)]
    run = passage_series_to_run(original, run_id="run:passages")
    assert run_to_passage_series(run)[0].passage == 12


def test_evidence_bundle_refuses_an_incompatible_canonical_run() -> None:
    """A bundle is what gets stored, transmitted and re-read, so it is the right boundary
    to refuse a run whose field meanings this reader cannot trust."""
    from datetime import UTC, datetime

    from virtualcell.literature.contracts import (
        LiteratureEvidenceBundle,
        LiteratureQuery,
        ProviderProvenance,
    )

    provenance = ProviderProvenance(
        provider="p", query_sent="q", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC)
    )
    query = LiteratureQuery(query_text="TERT")

    # A compatible run is accepted...
    LiteratureEvidenceBundle(query=query, provider_provenance=provenance, canonical_runs=[_run()])
    # ...an incompatible one is refused at the bundle boundary.
    with pytest.raises(ValueError, match="incompatible canonical experiment schema"):
        LiteratureEvidenceBundle(
            query=query,
            provider_provenance=provenance,
            canonical_runs=[_run(schema_version=f"{SCHEMA_MAJOR + 1}.0")],
        )
