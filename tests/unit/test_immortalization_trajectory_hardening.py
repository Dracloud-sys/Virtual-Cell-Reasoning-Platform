"""Adversarial trajectory tests from real long-culture validation (PR7 hardening).

Each test pins a pattern where the original engine misclassified the state,
diluted a signal, or produced an unusable derived trend, and asserts the hardened
behavior. Grouped by the review item that motivated it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.agents.immortalization.models import PassageObservation
from virtualcell.agents.immortalization.trajectory import (
    MarkerValue,
    SeriesQualityFlag,
    TrajectoryState,
    TrajectoryThresholds,
    extract_trajectory,
)


def _series(points) -> list[PassageObservation]:
    """(passage, cumulative_PDL, DT_hours) triples; None entries are omitted per axis."""
    return [PassageObservation(passage=p, cumulative_PDL=pdl, DT_hours=dt) for p, pdl, dt in points]


# --- High 0: terminal-anchored re_arrest -------------------------------------


def test_historical_crisis_then_terminal_growth_is_not_re_arrest() -> None:
    # F->G->F historically, then sustained terminal growth: NOT re_arrest.
    ta = extract_trajectory(
        _series(
            [
                (1, 1.0, 40),
                (2, 1.2, 60),
                (3, 3.0, 45),
                (4, 3.2, 70),
                (5, 5.0, 50),
                (6, 7.0, 48),
            ]
        )
    )
    assert ta.state is not TrajectoryState.RE_ARREST
    assert ta.state is TrajectoryState.RECOVERY_AFTER_PLATEAU
    assert ta.derived_PDL_trend is MarkerValue.INCREASING
    assert any("terminal" in r.lower() for r in ta.rationale)


def test_true_terminal_re_arrest_is_preserved() -> None:
    # Plateau -> recovery -> terminal arrest (ends flat): still re_arrest.
    ta = extract_trajectory(
        _series([(20, 20.0, 40), (25, 20.2, 78), (30, 23.0, 46), (35, 23.3, 95)])
    )
    assert ta.state is TrajectoryState.RE_ARREST


def test_re_arrest_plateau_interval_is_terminal_flat_only() -> None:
    # plateau_interval must be the final flat run, never spanning intervening growth.
    ta = extract_trajectory(
        _series([(20, 20.0, 40), (25, 20.2, 78), (30, 23.0, 46), (35, 23.3, 95)])
    )
    assert ta.state is TrajectoryState.RE_ARREST
    assert ta.recovery_interval == (25, 30)
    assert ta.plateau_interval == (30, 35)  # only the terminal flat interval


def test_terminal_growth_with_two_prior_plateaus_is_not_re_arrest() -> None:
    # Two historical plateaus, then long terminal growth: terminal state wins.
    ta = extract_trajectory(
        _series(
            [
                (1, 1.0, 40),
                (2, 1.2, 40),
                (3, 3.0, 40),
                (4, 3.2, 40),
                (5, 6.0, 40),
                (6, 9.0, 40),
                (7, 12.0, 40),
            ]
        )
    )
    assert ta.state is not TrajectoryState.RE_ARREST


# --- High 1: axis-specific usable timepoints ---------------------------------


def test_axis_specific_usable_counts_block_a_thin_trajectory() -> None:
    # 3 observations, but only 2 usable DT and 2 usable PDL (middle is empty).
    series = [
        PassageObservation(passage=1, cumulative_PDL=1, DT_hours=30),
        PassageObservation(passage=2),
        PassageObservation(passage=3, cumulative_PDL=3, DT_hours=60),
    ]
    ta = extract_trajectory(series)
    assert ta.usable_PDL_timepoints == 2
    assert ta.usable_DT_timepoints == 2
    assert ta.state is TrajectoryState.INSUFFICIENT_SERIES
    assert ta.derived_DT_trend is MarkerValue.UNKNOWN  # 2 DT points don't confirm a trend
    assert {SeriesQualityFlag.MISSING_DT, SeriesQualityFlag.MISSING_PDL} <= set(ta.quality_flags)


def test_partial_missing_dt_flag_with_full_pdl() -> None:
    series = [
        PassageObservation(passage=1, cumulative_PDL=1, DT_hours=30),
        PassageObservation(passage=2, cumulative_PDL=2),  # DT missing here
        PassageObservation(passage=3, cumulative_PDL=3, DT_hours=40),
        PassageObservation(passage=4, cumulative_PDL=4, DT_hours=41),
    ]
    ta = extract_trajectory(series)
    assert SeriesQualityFlag.MISSING_DT in ta.quality_flags
    assert ta.usable_DT_timepoints == 3
    assert ta.usable_PDL_timepoints == 4


def test_two_dt_points_do_not_yield_a_dt_trend() -> None:
    series = [
        PassageObservation(passage=1, cumulative_PDL=1, DT_hours=40),
        PassageObservation(passage=2, cumulative_PDL=2),
        PassageObservation(passage=3, cumulative_PDL=3, DT_hours=90),
    ]
    ta = extract_trajectory(series)
    assert ta.derived_DT_trend is MarkerValue.UNKNOWN
    assert ta.DT_fold_change is None


# --- Medium 3: sparse passage sampling ---------------------------------------


def test_sparse_uniform_gaps_flagged_not_irregular() -> None:
    # Gaps of 9,10: uniform (not irregular) but sparse.
    ta = extract_trajectory(_series([(1, 1.0, 30), (10, 1.8, 31), (20, 2.6, 32)]))
    assert SeriesQualityFlag.SPARSE_PASSAGE_SAMPLING in ta.quality_flags
    assert SeriesQualityFlag.IRREGULAR_PASSAGE_INTERVALS not in ta.quality_flags
    # PDL features are preserved even though the abs-gain plateau is low-confidence.
    assert ta.total_PDL_gain == 1.6


# --- Medium 4: DT stable band vs the ambiguous zone --------------------------


@pytest.mark.parametrize(
    "dts,expected",
    [
        ([40, 50, 50], "stable"),  # fold 1.25 -> boundary of the stable band
        ([40, 50, 56], "unknown"),  # fold 1.4 -> ambiguous, NOT stable
        ([40, 50, 60], "worsening"),  # fold 1.5 -> worsening threshold
        ([40, 40, 30], "improved"),  # fold 0.75 -> improving threshold
    ],
)
def test_dt_fold_boundaries(dts, expected) -> None:
    series = _series([(1, 1.0, dts[0]), (2, 2.0, dts[1]), (3, 3.0, dts[2])])
    assert extract_trajectory(series).derived_DT_trend.value == expected


# --- Medium 5: DT unknown must not be described as stable ---------------------


def test_dt_all_missing_pdl_increasing_rationale() -> None:
    series = [
        PassageObservation(passage=1, cumulative_PDL=1),
        PassageObservation(passage=2, cumulative_PDL=3),
        PassageObservation(passage=3, cumulative_PDL=5),
    ]
    ta = extract_trajectory(series)
    assert ta.state is TrajectoryState.STABLE_GROWTH  # name kept for API compatibility
    assert ta.derived_DT_trend is MarkerValue.UNKNOWN
    joined = " ".join(ta.rationale).lower()
    assert "unverified" in joined
    assert "stable or improving doubling time" not in joined


# --- Medium 6: terminal deterioration surfaced despite a benign overall trend -


def test_terminal_dt_deterioration_flagged_when_overall_trend_dilutes_it() -> None:
    # Long, DT-stable series with a single terminal spike: the whole-series median
    # stays stable, but the recent-window signal must fire.
    dts = [40] * 10 + [400]
    series = [
        PassageObservation(passage=i + 1, cumulative_PDL=1.0 + i, DT_hours=d)
        for i, d in enumerate(dts)
    ]
    ta = extract_trajectory(series)
    assert ta.derived_DT_trend is MarkerValue.STABLE  # overall trend not worsening
    assert ta.terminal_dt_deterioration is True  # but recent deterioration is surfaced


def test_no_terminal_deterioration_on_a_steady_series() -> None:
    series = [
        PassageObservation(passage=i + 1, cumulative_PDL=1.0 + i, DT_hours=40) for i in range(6)
    ]
    assert extract_trajectory(series).terminal_dt_deterioration is False


# --- Medium 4 (validation): threshold ordering -------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"improving_dt_fold_change": 1.5},  # > 1
        {"improving_dt_fold_change": 0.0},  # not > 0
        {"worsening_dt_fold_change": 0.9},  # < 1
        {"stable_dt_relative_change": 1.0},  # not < 1
        {"worsening_dt_fold_change": 1.1},  # below stable upper bound (1.25)
        {"improving_dt_fold_change": 0.9},  # above stable lower bound (0.75)
    ],
)
def test_thresholds_reject_inconsistent_ordering(kwargs) -> None:
    with pytest.raises(ValidationError):
        TrajectoryThresholds(**kwargs)
