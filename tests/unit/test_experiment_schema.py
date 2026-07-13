"""Tests for the canonical, source-neutral experiment schema (core.experiment)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from virtualcell.core.experiment import (
    AcquisitionMode,
    ElapsedTimePoint,
    ExperimentRun,
    Measurement,
    MeasurementQuality,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    SimulationStepTimePoint,
    TimestampTimePoint,
)


def _experiment_run() -> ExperimentRun:
    return ExperimentRun(
        run_id="RUN-1",
        provenance=Provenance(
            origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.MANUAL
        ),
        conditions={"medium": "DMEM", "serum_pct": 10},
        observations=[
            Observation(
                time_point=PassageTimePoint(value=20),
                measurements=[
                    Measurement(name="cumulative_PDL", value=22.0, unit="population_doubling"),
                    Measurement(name="DT_hours", value=42.0, unit="hour"),
                    Measurement(name="contaminated", value=False),
                ],
            )
        ],
        metadata={"note": "seed"},
    )


def test_experiment_manual_run_json_round_trips() -> None:
    run = _experiment_run()
    restored = ExperimentRun.model_validate(run.model_dump(mode="json"))
    assert restored == run
    # The discriminated union reconstitutes the concrete time-point type.
    assert isinstance(restored.observations[0].time_point, PassageTimePoint)
    # A boolean measurement value survives round-trip as a bool, not coerced to int.
    contaminated = restored.observations[0].measurements[2]
    assert contaminated.value is False


def test_simulation_imported_run_json_round_trips() -> None:
    run = ExperimentRun(
        run_id="SIM-7",
        provenance=Provenance(
            origin_kind=OriginKind.SIMULATION,
            acquisition_mode=AcquisitionMode.IMPORTED,
            source_system="virtualcell-sim",
            source_run_id="abc123",
        ),
        observations=[
            Observation(
                time_point=SimulationStepTimePoint(value=0),
                measurements=[Measurement(name="predicted_PDL", value=1.0)],
            ),
            Observation(
                time_point=SimulationStepTimePoint(value=100),
                measurements=[Measurement(name="predicted_PDL", value=5.0)],
            ),
        ],
    )
    restored = ExperimentRun.model_validate(run.model_dump(mode="json"))
    assert restored == run
    assert restored.provenance.origin_kind is OriginKind.SIMULATION


def test_passage_time_point_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        PassageTimePoint(value=-1)


def test_elapsed_time_unit_is_validated() -> None:
    assert ElapsedTimePoint(value=48, unit="hour").unit == "hour"
    with pytest.raises(ValidationError):
        ElapsedTimePoint(value=48, unit="fortnight")


def test_simulation_step_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        SimulationStepTimePoint(value=-5)


def test_timestamp_requires_timezone() -> None:
    TimestampTimePoint(value=datetime(2024, 1, 1, tzinfo=UTC))  # ok
    with pytest.raises(ValidationError, match="timezone-aware"):
        TimestampTimePoint(value=datetime(2024, 1, 1))  # naive -> rejected


def test_confidence_range_is_enforced() -> None:
    Measurement(name="x", value=1.0, confidence=0.5)
    with pytest.raises(ValidationError):
        Measurement(name="x", value=1.0, confidence=1.5)


def test_blank_measurement_name_rejected() -> None:
    with pytest.raises(ValidationError):
        Measurement(name="   ", value=1.0)


def test_value_quality_consistency() -> None:
    # A valid measurement must carry a value.
    with pytest.raises(ValidationError):
        Measurement(name="x", value=None, quality=MeasurementQuality.VALID)
    # A missing measurement must not carry a value.
    with pytest.raises(ValidationError):
        Measurement(name="x", value=1.0, quality=MeasurementQuality.MISSING)
    # A genuinely missing measurement is fine.
    assert Measurement(name="x", quality=MeasurementQuality.MISSING).value is None


def test_metadata_rejects_non_scalar_values() -> None:
    with pytest.raises(ValidationError):
        Provenance(
            origin_kind=OriginKind.EXPERIMENT,
            acquisition_mode=AcquisitionMode.MANUAL,
            metadata={"nested": {"not": "scalar"}},
        )


def test_run_id_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        ExperimentRun(
            run_id="  ",
            provenance=Provenance(
                origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.MANUAL
            ),
        )


def test_duplicate_time_points_are_preserved_as_replicates() -> None:
    # The canonical layer does not reject replicates; order and count are preserved.
    prov = Provenance(origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.MANUAL)
    run = ExperimentRun(
        run_id="R",
        provenance=prov,
        observations=[
            Observation(time_point=PassageTimePoint(value=10), measurements=[]),
            Observation(time_point=PassageTimePoint(value=10), measurements=[]),
        ],
    )
    assert [o.time_point.value for o in run.observations] == [10, 10]


def test_observation_allows_empty_measurements() -> None:
    # A time point with no usable measurements is allowed (the passage adapter emits
    # this when a PassageObservation carries neither PDL nor DT).
    obs = Observation(time_point=PassageTimePoint(value=5))
    assert obs.measurements == []
