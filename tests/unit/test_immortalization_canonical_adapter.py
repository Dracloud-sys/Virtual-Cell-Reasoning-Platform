"""Tests for the immortalization <-> canonical experiment adapter (PR8a)."""

from __future__ import annotations

import pytest

from virtualcell.agents.immortalization.adapters import (
    CanonicalAdapterError,
    canonical_to_passage_observation,
    passage_observation_to_canonical,
    passage_series_to_run,
    run_to_passage_series,
)
from virtualcell.agents.immortalization.models import PassageObservation
from virtualcell.agents.immortalization.trajectory import extract_trajectory
from virtualcell.core.experiment import (
    AcquisitionMode,
    ExperimentRun,
    Measurement,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    SimulationStepTimePoint,
)


def _obs(passage, pdl=None, dt=None) -> PassageObservation:
    return PassageObservation(passage=passage, cumulative_PDL=pdl, DT_hours=dt)


def _prov() -> Provenance:
    return Provenance(origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.MANUAL)


def _canonical(*measurements) -> Observation:
    return Observation(time_point=PassageTimePoint(value=25), measurements=list(measurements))


# --- forward / reverse -------------------------------------------------------


def test_passage_observation_to_canonical() -> None:
    obs = passage_observation_to_canonical(_obs(25, pdl=22.0, dt=42.0))
    assert isinstance(obs.time_point, PassageTimePoint)
    assert obs.time_point.value == 25
    by_name = {m.name: m for m in obs.measurements}
    assert by_name["cumulative_PDL"].value == 22.0
    assert by_name["cumulative_PDL"].unit == "population_doubling"
    assert by_name["DT_hours"].value == 42.0
    assert by_name["DT_hours"].unit == "hour"


def test_canonical_to_passage_observation() -> None:
    obs = canonical_to_passage_observation(
        _canonical(
            Measurement(name="cumulative_PDL", value=22.0, unit="population_doubling"),
            Measurement(name="DT_hours", value=42.0, unit="hour"),
        )
    )
    assert obs.passage == 25
    assert obs.cumulative_PDL == 22.0
    assert obs.DT_hours == 42.0


def test_passage_series_round_trips_through_a_run() -> None:
    series = [_obs(25, 22.0, 42.0), _obs(30, 25.5, 80.0), _obs(35, 27.0, 100.0)]
    run = passage_series_to_run(series, run_id="RUN-1")
    assert isinstance(run, ExperimentRun)
    assert run.provenance.origin_kind is OriginKind.EXPERIMENT
    restored = run_to_passage_series(run)
    assert restored == series


def test_cumulative_pdl_only() -> None:
    obs = passage_observation_to_canonical(_obs(25, pdl=22.0))
    assert [m.name for m in obs.measurements] == ["cumulative_PDL"]
    assert canonical_to_passage_observation(obs) == _obs(25, pdl=22.0)


def test_dt_hours_only() -> None:
    obs = passage_observation_to_canonical(_obs(25, dt=42.0))
    assert [m.name for m in obs.measurements] == ["DT_hours"]
    assert canonical_to_passage_observation(obs) == _obs(25, dt=42.0)


def test_both_measurements_missing_yields_empty_observation() -> None:
    obs = passage_observation_to_canonical(_obs(25))
    assert obs.measurements == []
    assert canonical_to_passage_observation(obs) == _obs(25)


# --- validation --------------------------------------------------------------


def test_non_passage_time_point_is_rejected() -> None:
    obs = Observation(
        time_point=SimulationStepTimePoint(value=3),
        measurements=[Measurement(name="cumulative_PDL", value=1.0)],
    )
    with pytest.raises(CanonicalAdapterError, match="passage time point"):
        canonical_to_passage_observation(obs)


def test_duplicate_canonical_measurement_is_rejected() -> None:
    obs = _canonical(
        Measurement(name="DT_hours", value=42.0, unit="hour"),
        Measurement(name="DT_hours", value=80.0, unit="hour"),
    )
    with pytest.raises(CanonicalAdapterError, match="duplicate"):
        canonical_to_passage_observation(obs)


def test_non_numeric_canonical_value_is_rejected() -> None:
    obs = _canonical(Measurement(name="DT_hours", value="fast", unit="hour"))
    with pytest.raises(CanonicalAdapterError, match="numeric"):
        canonical_to_passage_observation(obs)


def test_unsupported_unit_is_rejected_not_reinterpreted() -> None:
    obs = _canonical(Measurement(name="DT_hours", value=2.0, unit="day"))
    with pytest.raises(CanonicalAdapterError, match="unit"):
        canonical_to_passage_observation(obs)


def test_extra_measurement_is_rejected_when_strict_ignored_otherwise() -> None:
    obs = _canonical(
        Measurement(name="DT_hours", value=42.0, unit="hour"),
        Measurement(name="oxygen_pct", value=5.0),
    )
    with pytest.raises(CanonicalAdapterError, match="oxygen_pct"):
        canonical_to_passage_observation(obs, strict=True)
    # strict=False ignores the unmapped measurement (documented loss).
    lenient = canonical_to_passage_observation(obs, strict=False)
    assert lenient == _obs(25, dt=42.0)


def test_missing_unit_is_accepted() -> None:
    # A recognized measurement with no unit is accepted (no claim to reinterpret).
    obs = _canonical(Measurement(name="cumulative_PDL", value=22.0))
    assert canonical_to_passage_observation(obs).cumulative_PDL == 22.0


# --- interop with the existing pipeline --------------------------------------


def test_adapter_output_feeds_extract_trajectory() -> None:
    run = passage_series_to_run(
        [_obs(25, 22.0, 42.0), _obs(30, 25.5, 80.0), _obs(35, 27.0, 100.0)],
        run_id="RUN-1",
    )
    series = run_to_passage_series(run)
    ta = extract_trajectory(series)  # the adapter did no reasoning; the engine does
    assert ta.state.value == "progressive_slowdown"
    assert ta.derived_DT_trend.value == "worsening"
