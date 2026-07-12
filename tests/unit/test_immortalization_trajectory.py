"""Unit tests for the deterministic trajectory extraction engine (PR7b)."""

from __future__ import annotations

from virtualcell.agents.immortalization.models import PassageObservation
from virtualcell.agents.immortalization.trajectory import (
    SeriesQualityFlag,
    TrajectoryState,
    TrajectoryThresholds,
    extract_trajectory,
)


def _obs(**kw) -> PassageObservation:
    return PassageObservation(**kw)


def _series(points: list[tuple[int, float | None, float | None]]) -> list[PassageObservation]:
    """Build observations from (passage, cumulative_PDL, DT_hours) triples."""
    return [_obs(passage=p, cumulative_PDL=pdl, DT_hours=dt) for p, pdl, dt in points]


# --- state classification ----------------------------------------------------


def test_stable_growth() -> None:
    ta = extract_trajectory(_series([(20, 20.0, 30), (25, 24.0, 32), (30, 28.0, 31)]))
    assert ta.state is TrajectoryState.STABLE_GROWTH
    assert ta.derived_PDL_trend.value == "increasing"
    assert ta.derived_DT_trend.value == "stable"


def test_progressive_slowdown() -> None:
    ta = extract_trajectory(_series([(25, 22.0, 42), (30, 25.5, 80), (35, 27.0, 100)]))
    assert ta.state is TrajectoryState.PROGRESSIVE_SLOWDOWN
    assert ta.derived_DT_trend.value == "worsening"
    # The plan's worked example: 100/42 ≈ 2.38 with a single-point early/late window.
    assert ta.DT_fold_change == 2.38


def test_plateau() -> None:
    ta = extract_trajectory(_series([(28, 25.0, 60), (33, 25.3, 90), (38, 25.5, 120)]))
    assert ta.state is TrajectoryState.PLATEAU
    assert ta.derived_PDL_trend.value == "plateau"
    assert ta.plateau_interval == (28, 38)


def test_transient_recovery_single_interval() -> None:
    ta = extract_trajectory(
        _series([(20, 18.0, 34), (25, 22.0, 36), (30, 22.4, 70), (35, 25.0, 40)])
    )
    assert ta.state is TrajectoryState.TRANSIENT_RECOVERY
    assert ta.recovery_interval == (30, 35)
    assert any("durability" in r.lower() for r in ta.rationale)


def test_recovery_after_plateau_two_intervals() -> None:
    ta = extract_trajectory(
        _series([(20, 20.0, 40), (25, 20.3, 78), (30, 23.0, 44), (35, 26.0, 38)])
    )
    assert ta.state is TrajectoryState.RECOVERY_AFTER_PLATEAU
    assert ta.plateau_interval == (20, 25)
    assert ta.recovery_interval == (25, 35)


def test_re_arrest() -> None:
    ta = extract_trajectory(
        _series([(20, 20.0, 40), (25, 20.2, 78), (30, 23.0, 46), (35, 23.3, 95)])
    )
    assert ta.state is TrajectoryState.RE_ARREST
    assert ta.recovery_interval == (25, 30)
    assert ta.plateau_interval == (30, 35)


def test_conflicting_trajectory_pdl_stalls_dt_improves() -> None:
    ta = extract_trajectory(_series([(20, 25.0, 100), (25, 25.2, 70), (30, 25.3, 45)]))
    assert ta.state is TrajectoryState.CONFLICTING_TRAJECTORY
    assert ta.derived_DT_trend.value == "improved"


def test_insufficient_series_two_timepoints() -> None:
    ta = extract_trajectory(_series([(20, 20.0, 40), (25, 24.0, 42)]))
    assert ta.state is TrajectoryState.INSUFFICIENT_SERIES
    assert SeriesQualityFlag.INSUFFICIENT_TIMEPOINTS in ta.quality_flags


# --- features and quality flags ---------------------------------------------


def test_dt_fold_change_ignores_a_mid_series_outlier() -> None:
    # The early/late DT trend is read from the ends of the series, so a single
    # mid-series DT spike does not flip the trend (real trend vs one outlier).
    clean = extract_trajectory(
        _series([(20, 20.0, 40), (23, 22.0, 41), (26, 24.0, 40), (29, 26.0, 40), (32, 28.0, 41)])
    )
    spiked = extract_trajectory(
        _series([(20, 20.0, 40), (23, 22.0, 41), (26, 24.0, 200), (29, 26.0, 40), (32, 28.0, 41)])
    )
    assert clean.derived_DT_trend.value == "stable"
    assert spiked.derived_DT_trend.value == "stable"


def test_non_monotonic_pdl_is_a_quality_flag_not_an_error() -> None:
    ta = extract_trajectory(_series([(20, 25.0, 40), (25, 24.0, 42), (30, 26.0, 41)]))
    assert SeriesQualityFlag.NON_MONOTONIC_PDL in ta.quality_flags


def test_missing_dt_partial_analysis() -> None:
    ta = extract_trajectory(
        [
            _obs(passage=20, cumulative_PDL=20.0),
            _obs(passage=25, cumulative_PDL=24.0),
            _obs(passage=30, cumulative_PDL=28.0),
        ]
    )
    assert SeriesQualityFlag.MISSING_DT in ta.quality_flags
    assert ta.DT_fold_change is None
    # PDL-only series still yields a growth classification.
    assert ta.state is TrajectoryState.STABLE_GROWTH


def test_missing_pdl_cannot_classify_growth() -> None:
    ta = extract_trajectory(
        [
            _obs(passage=20, DT_hours=40),
            _obs(passage=25, DT_hours=60),
            _obs(passage=30, DT_hours=90),
        ]
    )
    assert SeriesQualityFlag.MISSING_PDL in ta.quality_flags
    assert ta.state is TrajectoryState.INSUFFICIENT_SERIES


def test_irregular_passage_intervals_flag() -> None:
    ta = extract_trajectory(_series([(20, 20.0, 40), (21, 24.0, 41), (60, 28.0, 42)]))
    assert SeriesQualityFlag.IRREGULAR_PASSAGE_INTERVALS in ta.quality_flags


def test_unsorted_input_is_sorted_for_analysis_without_mutation() -> None:
    obs = _series([(35, 27.0, 100), (25, 22.0, 42), (30, 25.5, 80)])
    ta = extract_trajectory(obs)
    # Correctly ordered analysis => progressive slowdown, first/last by passage.
    assert ta.state is TrajectoryState.PROGRESSIVE_SLOWDOWN
    assert (ta.first_passage, ta.last_passage) == (25, 35)
    # Caller's list order is unchanged.
    assert [o.passage for o in obs] == [35, 25, 30]


# --- threshold boundaries ----------------------------------------------------


def test_min_timepoints_threshold_is_configurable() -> None:
    two = _series([(20, 20.0, 40), (25, 24.0, 42)])
    relaxed = extract_trajectory(two, TrajectoryThresholds(min_timepoints=2))
    assert relaxed.state is not TrajectoryState.INSUFFICIENT_SERIES


def test_plateau_gain_boundary() -> None:
    # A per-interval PDL gain exactly at the plateau threshold counts as growth.
    t = TrajectoryThresholds()
    at_threshold = extract_trajectory(_series([(20, 20.0, 40), (25, 21.0, 41), (30, 22.0, 42)]), t)
    below = extract_trajectory(_series([(20, 20.0, 40), (25, 20.5, 41), (30, 21.0, 42)]), t)
    assert at_threshold.state is TrajectoryState.STABLE_GROWTH  # gain 1.0 >= 1.0
    assert below.state is TrajectoryState.PLATEAU  # gain 0.5 < 1.0
