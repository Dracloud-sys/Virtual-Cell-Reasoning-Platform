"""Passage-aware trajectory data contract (PR7a).

PR7 structures the time axis that single-snapshot labels used to discard: raw
per-passage DT/PDL series become a typed :class:`TrajectoryAssessment` that
separates *raw observations* from *derived interpretation*. This module defines
the contract only — the deterministic extraction engine (``extract_trajectory``)
lands in PR7b and the baseline integration in PR7c.

Every classification threshold is an explicit field on
:class:`TrajectoryThresholds`, not an implicit "DT increased a lot" judgment.
These values are a **v1 benchmark policy**, not a universal biological law.
"""

from __future__ import annotations

import math
from enum import StrEnum
from statistics import median

from pydantic import BaseModel, Field

from virtualcell.agents.immortalization.models import MarkerValue, PassageObservation


class TrajectoryThresholds(BaseModel):
    """Policy thresholds for trajectory classification (v1 benchmark, not a law)."""

    min_timepoints: int = 3
    stable_dt_relative_change: float = 0.25
    worsening_dt_fold_change: float = 1.50
    improving_dt_fold_change: float = 0.75
    plateau_pdl_gain: float = 1.0
    recovery_min_pdl_gain: float = 2.0
    min_recovery_intervals: int = 2


class SeriesQualityFlag(StrEnum):
    """Non-fatal quality concerns about a passage series (kept distinct from errors)."""

    INSUFFICIENT_TIMEPOINTS = "insufficient_timepoints"
    IRREGULAR_PASSAGE_INTERVALS = "irregular_passage_intervals"
    NON_MONOTONIC_PDL = "non_monotonic_pdl"
    MISSING_DT = "missing_dt"
    MISSING_PDL = "missing_pdl"
    SPARSE_LATE_PASSAGE = "sparse_late_passage"
    POSSIBLE_OUTLIER = "possible_outlier"


class TrajectoryState(StrEnum):
    """The proliferation-course classification (distinct from candidate status)."""

    INSUFFICIENT_SERIES = "insufficient_series"
    STABLE_GROWTH = "stable_growth"
    PROGRESSIVE_SLOWDOWN = "progressive_slowdown"
    PLATEAU = "plateau"
    RECOVERY_AFTER_PLATEAU = "recovery_after_plateau"
    TRANSIENT_RECOVERY = "transient_recovery"
    RE_ARREST = "re_arrest"
    CONFLICTING_TRAJECTORY = "conflicting_trajectory"


class TrajectoryAssessment(BaseModel):
    """Derived trajectory result — computed features only, never a copy of raw data."""

    state: TrajectoryState
    first_passage: int | None = None
    last_passage: int | None = None
    timepoint_count: int = 0
    derived_PDL_trend: MarkerValue = MarkerValue.UNKNOWN
    derived_DT_trend: MarkerValue = MarkerValue.UNKNOWN
    early_DT_median: float | None = None
    late_DT_median: float | None = None
    DT_fold_change: float | None = None
    total_PDL_gain: float | None = None
    plateau_interval: tuple[int, int] | None = None
    recovery_interval: tuple[int, int] | None = None
    quality_flags: list[SeriesQualityFlag] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


# --- Deterministic extraction engine (PR7b) ---------------------------------
#
# All judgment is threshold-driven (TrajectoryThresholds). The classification is
# structural: consecutive PDL observations are labelled "growing" or "flat", runs
# of like labels are compressed, and crisis/recovery patterns (which must not be
# overwritten by a simpler current state) are detected before the plain states.


def _window(n: int) -> int:
    """Size of the early/late median window: ~1/3 of the points, so a single
    outlier cannot flip the DT trend (>=1 for any non-empty series)."""
    return max(1, math.ceil(n / 3))


def _dt_trend(fold: float | None, t: TrajectoryThresholds) -> MarkerValue:
    if fold is None:
        return MarkerValue.UNKNOWN
    if fold >= t.worsening_dt_fold_change:
        return MarkerValue.WORSENING
    if fold <= t.improving_dt_fold_change:
        return MarkerValue.IMPROVED
    return MarkerValue.STABLE


def _runs(labels: list[str]) -> list[tuple[str, int, int]]:
    """Compress interval labels into (label, first_idx, last_idx) runs."""
    runs: list[tuple[str, int, int]] = []
    for i, label in enumerate(labels):
        if runs and runs[-1][0] == label:
            prev = runs[-1]
            runs[-1] = (label, prev[1], i)
        else:
            runs.append((label, i, i))
    return runs


def _span(pdl_passages: list[int], first_idx: int, last_idx: int) -> tuple[int, int]:
    """Passage span of an interval-index run: interval i joins point i and i+1."""
    return (pdl_passages[first_idx], pdl_passages[last_idx + 1])


def extract_trajectory(
    observations: list[PassageObservation],
    thresholds: TrajectoryThresholds | None = None,
) -> TrajectoryAssessment:
    """Derive a deterministic :class:`TrajectoryAssessment` from a passage series.

    Sorts a *copy* by passage (the input is never mutated), computes DT/PDL
    features, and classifies the proliferation course. Insufficient or missing
    axes degrade gracefully to quality flags rather than raising.
    """
    t = thresholds or TrajectoryThresholds()
    ordered = sorted(observations, key=lambda o: o.passage)
    n = len(ordered)
    flags: list[SeriesQualityFlag] = []
    rationale: list[str] = []

    first_passage = ordered[0].passage if ordered else None
    last_passage = ordered[-1].passage if ordered else None

    # Irregular passage spacing (informational; median-window smoothing still applies).
    passages = [o.passage for o in ordered]
    deltas = [b - a for a, b in zip(passages, passages[1:], strict=False)]
    if deltas and max(deltas) > 1.5 * min(deltas):
        flags.append(SeriesQualityFlag.IRREGULAR_PASSAGE_INTERVALS)

    # DT features (median-smoothed early vs late).
    dt = [(o.passage, o.DT_hours) for o in ordered if o.DT_hours is not None]
    early_dt = late_dt = fold = None
    if len(dt) >= 2:
        w = _window(len(dt))
        early_dt = median([v for _, v in dt[:w]])
        late_dt = median([v for _, v in dt[-w:]])
        fold = late_dt / early_dt
    else:
        flags.append(SeriesQualityFlag.MISSING_DT)
    dt_trend = _dt_trend(fold, t)

    # PDL features and per-interval growth/flat labels.
    pdl = [(o.passage, o.cumulative_PDL) for o in ordered if o.cumulative_PDL is not None]
    total_pdl_gain = None
    if len(pdl) >= 2:
        total_pdl_gain = pdl[-1][1] - pdl[0][1]
        if any(b < a for (_, a), (_, b) in zip(pdl, pdl[1:], strict=False)):
            flags.append(SeriesQualityFlag.NON_MONOTONIC_PDL)
    else:
        flags.append(SeriesQualityFlag.MISSING_PDL)

    base = {
        "first_passage": first_passage,
        "last_passage": last_passage,
        "timepoint_count": n,
        "early_DT_median": early_dt,
        "late_DT_median": late_dt,
        "DT_fold_change": round(fold, 2) if fold is not None else None,
        "total_PDL_gain": round(total_pdl_gain, 3) if total_pdl_gain is not None else None,
        "derived_DT_trend": dt_trend,
        "quality_flags": flags,
    }

    # A trajectory needs enough timepoints and a usable PDL series to classify.
    if n < t.min_timepoints:
        flags.append(SeriesQualityFlag.INSUFFICIENT_TIMEPOINTS)
        rationale.append(f"Only {n} timepoint(s); >= {t.min_timepoints} needed for a trajectory.")
        return TrajectoryAssessment(
            state=TrajectoryState.INSUFFICIENT_SERIES, rationale=rationale, **base
        )
    if len(pdl) < 2:
        rationale.append("Fewer than two PDL observations; cannot derive a growth course.")
        return TrajectoryAssessment(
            state=TrajectoryState.INSUFFICIENT_SERIES, rationale=rationale, **base
        )

    pdl_passages = [p for p, _ in pdl]
    gains = [b - a for (_, a), (_, b) in zip(pdl, pdl[1:], strict=False)]
    labels = ["G" if g >= t.plateau_pdl_gain else "F" for g in gains]
    runs = _runs(labels)
    pdl_trend = MarkerValue.INCREASING if labels[-1] == "G" else MarkerValue.PLATEAU
    base["derived_PDL_trend"] = pdl_trend

    growth_runs = [r for r in runs if r[0] == "G"]
    flat_runs = [r for r in runs if r[0] == "F"]

    # 1) Re-arrest: a growth run bracketed by flats (plateau -> recovery -> arrest).
    for k, run in enumerate(runs):
        if (
            run[0] == "G"
            and any(r[0] == "F" for r in runs[:k])
            and any(r[0] == "F" for r in runs[k + 1 :])
        ):
            rationale.append("Plateau, then recovery, then arrest again.")
            return TrajectoryAssessment(
                state=TrajectoryState.RE_ARREST,
                recovery_interval=_span(pdl_passages, run[1], run[2]),
                plateau_interval=_span(pdl_passages, runs[k + 1][1], runs[-1][2]),
                rationale=rationale,
                **base,
            )

    # A recovery is a final growth run preceded by a plateau.
    last_run = runs[-1]
    plateau_before = last_run[0] == "G" and any(r[0] == "F" for r in runs[:-1])
    if plateau_before:
        recovery_len = last_run[2] - last_run[1] + 1
        recovery_gain = sum(gains[last_run[1] : last_run[2] + 1])
        recovery_span = _span(pdl_passages, last_run[1], last_run[2])
        prev_flat = [r for r in runs[:-1] if r[0] == "F"][-1]
        plateau_span = _span(pdl_passages, prev_flat[1], prev_flat[2])
        # 2) Durable recovery: >= min intervals AND enough cumulative PDL regained.
        if recovery_len >= t.min_recovery_intervals and recovery_gain >= t.recovery_min_pdl_gain:
            rationale.append("Plateau followed by sustained recovery over multiple intervals.")
            return TrajectoryAssessment(
                state=TrajectoryState.RECOVERY_AFTER_PLATEAU,
                plateau_interval=plateau_span,
                recovery_interval=recovery_span,
                rationale=rationale,
                **base,
            )
        # 3) Transient recovery: recovery observed but durability not established.
        rationale.append("Recovery is observed but durability is not yet established.")
        return TrajectoryAssessment(
            state=TrajectoryState.TRANSIENT_RECOVERY,
            plateau_interval=plateau_span,
            recovery_interval=recovery_span,
            rationale=rationale,
            **base,
        )

    # 4) Ends flat: plateau — unless DT is improving against a stalled PDL (conflict).
    if last_run[0] == "F":
        if dt_trend == MarkerValue.IMPROVED:
            rationale.append(
                "PDL has stalled while the doubling time improves; directions disagree."
            )
            return TrajectoryAssessment(
                state=TrajectoryState.CONFLICTING_TRAJECTORY, rationale=rationale, **base
            )
        rationale.append("Population doublings have essentially stopped.")
        plateau_run = flat_runs[-1]
        return TrajectoryAssessment(
            state=TrajectoryState.PLATEAU,
            plateau_interval=_span(pdl_passages, flat_runs[0][1], plateau_run[2]),
            rationale=rationale,
            **base,
        )

    # 5) Growing to the end, no plateau-recovery structure: slowdown vs stable growth.
    if dt_trend == MarkerValue.WORSENING:
        rationale.append("PDL keeps rising but the doubling time progressively worsens.")
        return TrajectoryAssessment(
            state=TrajectoryState.PROGRESSIVE_SLOWDOWN, rationale=rationale, **base
        )
    if dt_trend in (MarkerValue.STABLE, MarkerValue.IMPROVED, MarkerValue.UNKNOWN):
        rationale.append("PDL increases with a stable or improving doubling time.")
        return TrajectoryAssessment(
            state=TrajectoryState.STABLE_GROWTH, rationale=rationale, **base
        )

    # 6) Fallback: signals that do not fit a named state.
    _ = growth_runs  # structural runs are captured in the intervals above
    rationale.append("Trajectory signals do not fit a single named state.")
    return TrajectoryAssessment(
        state=TrajectoryState.CONFLICTING_TRAJECTORY, rationale=rationale, **base
    )
