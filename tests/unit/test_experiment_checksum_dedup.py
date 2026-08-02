"""Run integrity and identity (PR13a, schema 1.1).

Two hashes answer two different questions, and the tests are organised that way:

* :func:`content_checksum` — "was this run modified?" Covers everything the run says,
  works at any declared version, and excludes the seal from its own input.
* :func:`dedup_key` — "do I already have this measurement?" Covers only what the run
  observed, and **refuses** a version whose field set this reader does not fully know.

The ordering rules are pinned explicitly rather than left to whatever the serializer
happens to do, because a hash that quietly depends on list order is a dedup bug waiting
for its first replicate.
"""

from __future__ import annotations

import math

import pytest

from virtualcell.core.experiment import (
    SCHEMA_MAJOR,
    SCHEMA_MINOR,
    SCHEMA_VERSION,
    AcquisitionMode,
    DedupUnavailableError,
    ExperimentRun,
    Measurement,
    MeasurementQuality,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    SchemaVersionError,
    content_checksum,
    dedup_key,
    deduplicate_runs,
)

NEWER_MINOR = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR + 999}"
OTHER_MAJOR = f"{SCHEMA_MAJOR + 1}.0"


def _provenance(**over) -> Provenance:
    fields = {
        "origin_kind": OriginKind.EXPERIMENT,
        "acquisition_mode": AcquisitionMode.MANUAL,
        "source_system": "lab-notebook",
        "source_run_id": "nb-42",
        "method": "manual_count",
    }
    fields.update(over)
    return Provenance(**fields)


def _observation(passage: int = 12, **over) -> Observation:
    fields = {
        "time_point": PassageTimePoint(value=passage),
        "measurements": [
            Measurement(name="cumulative_PDL", value=24.0, unit="population_doubling"),
            Measurement(name="DT_hours", value=40.0, unit="hour"),
        ],
    }
    fields.update(over)
    return Observation(**fields)


def _run(**over) -> ExperimentRun:
    fields = {
        "schema_version": SCHEMA_VERSION,
        "run_id": "test:1",
        "provenance": _provenance(),
        "conditions": {"medium": "DMEM", "serum_pct": 10},
        "observations": [_observation()],
    }
    fields.update(over)
    return ExperimentRun(**fields)


# --- the additive version bump ------------------------------------------------


def test_the_checksum_field_arrived_as_a_minor_bump() -> None:
    """A new optional field is additive, so by this schema's own policy it is a MINOR
    increment — the first real exercise of the compatibility rule PR12 wrote down."""
    assert (SCHEMA_MAJOR, SCHEMA_MINOR) == (1, 1)
    assert SCHEMA_VERSION == "1.1"
    assert _run().checksum is None  # absent means "not sealed", never "verified"


def test_a_run_at_the_previous_minor_is_still_readable_and_dedupable() -> None:
    older = _run(schema_version="1.0")
    assert older.schema_is_compatible
    older.require_compatible_schema()
    assert dedup_key(older) == dedup_key(_run())  # the version is not part of identity


# --- content_checksum: the integrity question ---------------------------------


def test_the_checksum_is_stable_across_processes() -> None:
    """A golden vector. If this changes, the hashing *input* changed — which silently
    invalidates every checksum ever stored, so it must never happen by accident."""
    assert content_checksum(_run()) == (
        "sha256:b25b7ca1c9856f15d804a63687da4da84caf625575d4a45450cbb4f2ab338120"
    )


def test_sealing_a_run_records_its_own_checksum() -> None:
    sealed = _run().sealed()
    assert sealed.checksum == content_checksum(sealed)


def test_the_checksum_excludes_the_checksum_field_itself() -> None:
    """Self-reference would make the seal unsatisfiable: writing the checksum into the run
    changes the run, so no value could ever equal the hash of the run containing it."""
    run = _run()
    assert content_checksum(run.sealed()) == content_checksum(run)


def test_a_sealed_run_survives_a_json_round_trip() -> None:
    sealed = _run().sealed()
    restored = ExperimentRun.model_validate(sealed.model_dump(mode="json"))
    assert restored == sealed
    assert restored.checksum == sealed.checksum


def test_a_tampered_run_no_longer_validates() -> None:
    payload = _run().sealed().model_dump(mode="json")
    payload["observations"][0]["measurements"][0]["value"] = 99.0
    with pytest.raises(ValueError, match="modified after it was sealed"):
        ExperimentRun.model_validate(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "test:2"},
        {"metadata": {"note": "second import"}},
        {"conditions": {"medium": "DMEM", "serum_pct": 5}},
        {"observations": [_observation(passage=13)]},
    ],
)
def test_any_change_to_what_the_run_says_changes_the_checksum(change: dict) -> None:
    assert content_checksum(_run(**change)) != content_checksum(_run())


def test_the_checksum_works_at_a_version_this_reader_does_not_know() -> None:
    """Hashing bytes needs no understanding of the fields — the difference from dedup."""
    payload = _run(schema_version=NEWER_MINOR).model_dump(mode="json")
    payload["operator_id"] = "tech-7"  # an additive field from that newer minor
    run = ExperimentRun.model_validate(payload)
    assert content_checksum(run).startswith("sha256:")
    # ...and the preserved unknown field is part of the integrity claim.
    assert content_checksum(run) != content_checksum(_run(schema_version=NEWER_MINOR))


# --- dedup_key: the identity question -----------------------------------------


def test_the_dedup_key_is_stable_across_processes() -> None:
    assert dedup_key(_run()) == (
        "sha256:9e3bca6a6c45e27a84b0dc5328aa8eff2e62bda67235b5a158e3a144c4c9c710"
    )


def test_two_imports_of_the_same_data_share_a_dedup_key() -> None:
    """The fields that differ between imports are exactly the ones identity ignores."""
    from datetime import UTC, datetime

    other = _run(
        run_id="test:reimported",
        metadata={"imported_by": "batch-2"},
        provenance=_provenance(
            recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
            metadata={"ticket": "OPS-9"},
        ),
        observations=[_observation(observation_id="obs-b")],
    )
    assert dedup_key(other) == dedup_key(_run())
    assert content_checksum(other) != content_checksum(_run())


@pytest.mark.parametrize(
    "change",
    [
        {"observations": [_observation(passage=13)]},
        {"conditions": {"medium": "DMEM", "serum_pct": 5}},
        {
            "observations": [
                _observation(
                    measurements=[Measurement(name="cumulative_PDL", value=25.0)],
                )
            ]
        },
    ],
)
def test_different_observations_get_different_dedup_keys(change: dict) -> None:
    assert dedup_key(_run(**change)) != dedup_key(_run())


def test_a_simulation_and_an_experiment_with_identical_numbers_are_not_duplicates() -> None:
    """Run-level provenance says *what kind of thing* the run is, so it is part of
    identity — unlike the nested provenance that only says where a datum came from."""
    simulated = _run(provenance=_provenance(origin_kind=OriginKind.SIMULATION))
    assert dedup_key(simulated) != dedup_key(_run())


# --- ordering and normalization rules, stated explicitly ----------------------


def test_observation_order_is_significant() -> None:
    """The sequence is the trajectory; reordering it changes what the run means."""
    forward = _run(observations=[_observation(passage=10), _observation(passage=20)])
    reversed_ = _run(observations=[_observation(passage=20), _observation(passage=10)])
    assert dedup_key(forward) != dedup_key(reversed_)


def test_measurement_order_within_an_observation_is_not_significant() -> None:
    """Readings taken at one time point are an unordered multiset, not a sequence."""
    pdl = Measurement(name="cumulative_PDL", value=24.0, unit="population_doubling")
    dt = Measurement(name="DT_hours", value=40.0, unit="hour")
    assert dedup_key(_run(observations=[_observation(measurements=[pdl, dt])])) == dedup_key(
        _run(observations=[_observation(measurements=[dt, pdl])])
    )


def test_measurement_multiplicity_is_significant() -> None:
    """Measurements are a *multiset*: two readings of the same value at one time point are
    replicates, and a run with two is not the same experiment as a run with one. This is
    where they differ from ``quality_flags``, which are a true set."""
    reading = Measurement(name="cumulative_PDL", value=24.0, unit="population_doubling")
    once = _run(observations=[_observation(measurements=[reading])])
    twice = _run(observations=[_observation(measurements=[reading, reading])])
    assert dedup_key(once) != dedup_key(twice)


def test_quality_flag_repeats_are_normalized_away() -> None:
    """A true set: a flag repeated twice says exactly what it says once."""

    def flagged(*flags: str) -> ExperimentRun:
        return _run(
            observations=[
                _observation(
                    measurements=[
                        Measurement(
                            name="cumulative_PDL",
                            value=24.0,
                            quality=MeasurementQuality.SUSPECT,
                            quality_flags=list(flags),
                        )
                    ]
                )
            ]
        )

    assert dedup_key(flagged("bound:>", "bound:>")) == dedup_key(flagged("bound:>"))


def test_quality_flag_order_is_not_significant() -> None:
    def flagged(*flags: str) -> ExperimentRun:
        return _run(
            observations=[
                _observation(
                    measurements=[
                        Measurement(
                            name="cumulative_PDL",
                            value=24.0,
                            quality=MeasurementQuality.SUSPECT,
                            quality_flags=list(flags),
                        )
                    ]
                )
            ]
        )

    assert dedup_key(flagged("bound:>", "uncertainty:0.5")) == dedup_key(
        flagged("uncertainty:0.5", "bound:>")
    )


def test_condition_key_order_is_not_significant() -> None:
    assert dedup_key(_run(conditions={"serum_pct": 10, "medium": "DMEM"})) == dedup_key(_run())


def test_where_a_condition_is_declared_is_part_of_identity() -> None:
    """A run-level condition asserts it held for the *whole* run; the same key on one
    observation asserts something narrower. They are different statements."""
    at_run_level = _run(conditions={"oxygen_pct": 5}, observations=[_observation()])
    at_observation_level = _run(
        conditions={},
        observations=[_observation(conditions={"oxygen_pct": 5})],
    )
    assert dedup_key(at_run_level) != dedup_key(at_observation_level)


# --- only finite numbers ------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_measurement_value_must_be_finite(bad: float) -> None:
    """NaN is not JSON, and ``NaN != NaN`` breaks the equality this schema depends on:
    a run holding one would not even equal itself."""
    with pytest.raises(ValueError, match="finite"):
        Measurement(name="PDL", value=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_scalar_maps_must_hold_finite_numbers(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _run(conditions={"oxygen_pct": bad})
    with pytest.raises(ValueError, match="finite"):
        _run(metadata={"drift": bad})
    with pytest.raises(ValueError, match="finite"):
        _run(observations=[_observation(conditions={"oxygen_pct": bad})])
    with pytest.raises(ValueError, match="finite"):
        _provenance(metadata={"ambient_c": bad})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_numeric_schema_fields_must_be_finite(bad: float) -> None:
    from virtualcell.core.experiment import ElapsedTimePoint

    with pytest.raises(ValueError):
        ElapsedTimePoint(value=bad, unit="hour")
    with pytest.raises(ValueError):
        Measurement(name="PDL", value=1.0, confidence=bad)


def test_a_sealed_run_survives_the_json_text_round_trip_it_claims() -> None:
    """The seal is only meaningful if the run can actually make the trip: serialize to real
    JSON text, parse it back, and the checksum must still verify."""
    import json as _json

    sealed = _run().sealed()
    text = sealed.model_dump_json()
    assert "NaN" not in text and "Infinity" not in text
    restored = ExperimentRun.model_validate(_json.loads(text))
    assert restored.checksum == sealed.checksum
    assert content_checksum(restored) == sealed.checksum


def test_hashing_refuses_a_non_finite_value_smuggled_in_as_a_newer_minor_extra() -> None:
    """Extras are preserved unvalidated by design, and Python's json module *accepts* the
    non-standard NaN token — so the hash needs its own guard, not just field validation."""
    import json as _json

    assert math.isnan(_json.loads('{"drift": NaN}')["drift"])  # this is how one gets in

    payload = _run(schema_version=NEWER_MINOR).model_dump(mode="json")
    payload["sensor_drift"] = float("nan")
    run = ExperimentRun.model_validate(payload)  # preserved, not judged

    # Checking after serialization would be too late in the way that matters: pydantic's
    # JSON mode rewrites the value to null, so a NaN-bearing run and a null-bearing run
    # would seal identically and the checksum would certify data it had already altered.
    assert run.model_dump(mode="json")["sensor_drift"] is None

    with pytest.raises(ValueError, match="non-finite"):
        content_checksum(run)


# --- numeric identity ---------------------------------------------------------


def _valued(value) -> ExperimentRun:
    return _run(observations=[_observation(measurements=[Measurement(name="PDL", value=value)])])


def test_an_integer_and_its_float_spelling_are_the_same_measurement() -> None:
    """``Measurement.numeric_value`` reads both as 1.0, so identity must agree. Two
    producers spelling one reading differently — a CSV reader emitting int, the literature
    converter emitting float — must land in the same dedup group."""
    assert dedup_key(_valued(1)) == dedup_key(_valued(1.0))


def test_signed_and_unsigned_zero_are_the_same_quantity() -> None:
    assert dedup_key(_valued(0)) == dedup_key(_valued(0.0)) == dedup_key(_valued(-0.0))


def test_condition_numbers_are_normalized_too() -> None:
    assert dedup_key(_run(conditions={"serum_pct": 10})) == dedup_key(
        _run(conditions={"serum_pct": 10.0})
    )


def test_non_integral_values_are_untouched() -> None:
    assert dedup_key(_valued(1.5)) != dedup_key(_valued(1))
    assert dedup_key(_valued(1.5)) == dedup_key(_valued(1.5))


def test_a_boolean_is_never_the_same_as_a_number() -> None:
    # ``isinstance(True, int)`` is a Python accident, not a statement about the data.
    assert dedup_key(_valued(True)) != dedup_key(_valued(1))


def test_the_checksum_deliberately_does_not_normalize_numbers() -> None:
    """Integrity asks whether the bytes changed, and ``1`` and ``1.0`` are different bytes.
    Identity asks whether the measurement is the same, and they are."""
    assert content_checksum(_valued(1)) != content_checksum(_valued(1.0))
    assert dedup_key(_valued(1)) == dedup_key(_valued(1.0))


# --- dedup refuses to guess ---------------------------------------------------


def test_a_newer_minor_cannot_be_deduplicated() -> None:
    """The hash covers the field set this reader knows. A newer minor may have added the
    very field that tells two runs apart, so 'cannot decide' must not be read as 'same'."""
    with pytest.raises(DedupUnavailableError, match="newer than this reader"):
        dedup_key(_run(schema_version=NEWER_MINOR))


def test_an_incompatible_major_cannot_be_deduplicated() -> None:
    with pytest.raises(DedupUnavailableError):
        dedup_key(_run(schema_version=OTHER_MAJOR))
    # Still a SchemaVersionError, so existing version handling catches it.
    assert issubclass(DedupUnavailableError, SchemaVersionError)


# --- deduplicate_runs ---------------------------------------------------------


def test_a_byte_identical_reimport_collapses_quietly() -> None:
    """One record seen twice is housekeeping, so there is nothing for a human to look at."""
    result = deduplicate_runs([_run(run_id="test:a"), _run(run_id="test:a")])

    assert [run.run_id for run in result.runs] == ["test:a"]
    assert result.collapsed == ["test:a"]
    assert result.collisions == []


def test_duplicates_collapse_to_the_first_run_in_input_order() -> None:
    result = deduplicate_runs([_run(run_id="test:a"), _run(run_id="test:b"), _run(run_id="test:c")])
    assert [run.run_id for run in result.runs] == ["test:a"]
    assert result.collapsed == ["test:b", "test:c"]


def test_a_same_key_different_checksum_collapse_is_reported_structurally() -> None:
    """Reported as a record, not a warning string, so a caller can act on it. ``run_id`` is
    in the checksum but not the key, so two *distinct records* asserting the same
    observations always surface here — two records making one claim is a fact about the
    data, not housekeeping."""
    kept = _run(run_id="test:a")
    dropped = _run(run_id="test:b", metadata={"imported_by": "batch-2"})
    result = deduplicate_runs([kept, dropped])

    assert [run.run_id for run in result.runs] == ["test:a"]
    assert result.collapsed == ["test:b"]
    assert len(result.collisions) == 1
    collision = result.collisions[0]
    assert (collision.kept_run_id, collision.dropped_run_id) == ("test:a", "test:b")
    assert collision.dedup_key == dedup_key(kept)
    assert collision.kept_checksum == content_checksum(kept)
    assert collision.dropped_checksum == content_checksum(dropped)
    assert collision.kept_checksum != collision.dropped_checksum


def test_an_undedupable_run_is_kept_never_dropped() -> None:
    """Being unable to prove two runs are duplicates is a reason to hold both."""
    known = _run(run_id="test:a")
    unknown = _run(run_id="test:newer", schema_version=NEWER_MINOR)
    result = deduplicate_runs([known, unknown, _run(run_id="test:dup")])

    assert [run.run_id for run in result.runs] == ["test:a", "test:newer"]
    assert result.not_deduplicated == ["test:newer"]
    assert result.collapsed == ["test:dup"]


def test_deduplication_is_deterministic() -> None:
    runs = [_run(run_id="test:a"), _run(run_id="test:b"), _run(run_id="test:c")]
    assert deduplicate_runs(runs) == deduplicate_runs(runs)


def test_deduplication_of_nothing_is_empty_not_an_error() -> None:
    result = deduplicate_runs([])
    assert (result.runs, result.collapsed, result.collisions) == ([], [], [])


# --- the literature ingestion consumer ----------------------------------------


def _literature_run(candidate: str, value: float, **over) -> ExperimentRun:
    """A run shaped like the ones literature.canonical produces."""
    fields = {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"literature:{candidate}",
        "provenance": Provenance(
            origin_kind=OriginKind.EXPERIMENT,
            acquisition_mode=AcquisitionMode.IMPORTED,
            source_system="literature",
            source_run_id="doi:10.1/x",
            metadata={"candidate_id": candidate},
        ),
        "observations": [
            Observation(
                time_point=PassageTimePoint(value=35),
                measurements=[Measurement(name="TERT", value=value)],
            )
        ],
    }
    fields.update(over)
    return ExperimentRun(**fields)


def test_ingestion_writes_one_measurement_once_and_names_the_duplicate() -> None:
    from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
    from virtualcell.literature.ingestion import ingest_runs

    store = InMemoryKnowledgeStore()
    report = ingest_runs(store, [_literature_run("c1", 1.0), _literature_run("c2", 1.0)])

    assert report.runs_ingested == 1
    assert report.collapsed_duplicates == ["literature:c2"]
    # Same observations, different candidate provenance — worth a human's attention.
    assert [c.dropped_run_id for c in report.collisions] == ["literature:c2"]


def test_ingestion_keeps_distinct_measurements() -> None:
    from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
    from virtualcell.literature.ingestion import ingest_runs

    store = InMemoryKnowledgeStore()
    report = ingest_runs(store, [_literature_run("c1", 1.0), _literature_run("c2", 2.0)])

    assert report.runs_ingested == 2
    assert report.collapsed_duplicates == []


def test_ingestion_reports_a_run_it_could_not_deduplicate() -> None:
    """Readable and dedupable are separate questions: a newer minor passes the schema
    check but blocks a dedup decision, so it is ingested and flagged, not assumed unique."""
    from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
    from virtualcell.literature.ingestion import ingest_runs

    store = InMemoryKnowledgeStore()
    report = ingest_runs(
        store,
        [_literature_run("c1", 1.0), _literature_run("c2", 1.0, schema_version=NEWER_MINOR)],
    )

    assert report.runs_ingested == 2
    assert report.not_deduplicated == ["literature:c2"]
    assert report.collapsed_duplicates == []
