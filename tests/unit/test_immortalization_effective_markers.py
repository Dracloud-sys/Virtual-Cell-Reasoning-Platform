"""Tests for snapshot ⊕ time-series marker reconciliation (PR7c)."""

from __future__ import annotations

from virtualcell.agents.immortalization.effective_markers import reconcile_markers
from virtualcell.agents.immortalization.models import (
    ImmortalizationAssessmentInput,
    MarkerValue,
)
from virtualcell.agents.immortalization.trajectory import TrajectoryAssessment, TrajectoryState


def _input(**kw) -> ImmortalizationAssessmentInput:
    return ImmortalizationAssessmentInput(intent="immortalization_assessment", **kw)


def _traj(state: TrajectoryState, pdl=MarkerValue.UNKNOWN, dt=MarkerValue.UNKNOWN):
    return TrajectoryAssessment(state=state, derived_PDL_trend=pdl, derived_DT_trend=dt)


def test_no_trajectory_leaves_snapshot_unchanged() -> None:
    data = _input(DT_trend="stable", PDL_trend="increasing")
    markers, derived, conflicts = reconcile_markers(data, None)
    assert markers["DT_trend"] == MarkerValue.STABLE
    assert derived == {}
    assert conflicts == []


def test_insufficient_series_does_not_override() -> None:
    data = _input(DT_trend="stable")
    traj = _traj(TrajectoryState.INSUFFICIENT_SERIES, dt=MarkerValue.WORSENING)
    markers, derived, conflicts = reconcile_markers(data, traj)
    assert markers["DT_trend"] == MarkerValue.STABLE  # not overridden
    assert derived == {}


def test_derived_trend_overrides_and_is_recorded() -> None:
    data = _input()  # no snapshot trends
    traj = _traj(
        TrajectoryState.PROGRESSIVE_SLOWDOWN,
        pdl=MarkerValue.INCREASING,
        dt=MarkerValue.WORSENING,
    )
    markers, derived, conflicts = reconcile_markers(data, traj)
    assert markers["DT_trend"] == MarkerValue.WORSENING
    assert markers["PDL_trend"] == MarkerValue.INCREASING
    assert derived == {"PDL_trend": "increasing", "DT_trend": "worsening"}
    assert conflicts == []  # nothing to conflict with (snapshot was unknown)


def test_adverse_crossing_surfaces_a_conflict() -> None:
    # Snapshot says the doubling time is stable; the raw series says worsening.
    data = _input(DT_trend="stable")
    traj = _traj(TrajectoryState.PROGRESSIVE_SLOWDOWN, dt=MarkerValue.WORSENING)
    markers, derived, conflicts = reconcile_markers(data, traj)
    assert markers["DT_trend"] == MarkerValue.WORSENING  # series wins
    assert len(conflicts) == 1
    assert "stable" in conflicts[0] and "worsening" in conflicts[0]


def test_same_side_update_is_not_a_conflict() -> None:
    # stable -> improved: both non-adverse; the value updates but no conflict.
    data = _input(DT_trend="stable")
    traj = _traj(TrajectoryState.RECOVERY_AFTER_PLATEAU, dt=MarkerValue.IMPROVED)
    markers, derived, conflicts = reconcile_markers(data, traj)
    assert markers["DT_trend"] == MarkerValue.IMPROVED
    assert derived["DT_trend"] == "improved"
    assert conflicts == []


def test_unknown_derived_trend_keeps_snapshot() -> None:
    # A PDL-less series derives no PDL trend, so the snapshot PDL_trend survives.
    data = _input(PDL_trend="increasing")
    traj = _traj(TrajectoryState.PLATEAU, pdl=MarkerValue.UNKNOWN, dt=MarkerValue.WORSENING)
    markers, derived, conflicts = reconcile_markers(data, traj)
    assert markers["PDL_trend"] == MarkerValue.INCREASING
    assert "PDL_trend" not in derived
