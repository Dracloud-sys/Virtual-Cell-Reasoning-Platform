"""Passage-aware trajectory data contract and extraction engine (PR7, hardened).

PR7 structures the time axis that single-snapshot labels used to discard: raw
per-passage DT/PDL series become a typed :class:`TrajectoryAssessment` that
separates *raw observations* from *derived interpretation*.

Every classification threshold is an explicit field on
:class:`TrajectoryThresholds`, not an implicit "DT increased a lot" judgment.
These values are a **v1 benchmark policy**, not a universal biological law.

Hardening (post real long-culture validation):

* Quality gating is **axis-specific**: usable PDL and usable DT are counted
  separately, and a derived trend is produced only when *its own* axis has enough
  usable timepoints. A partial-missing axis raises `MISSING_DT` / `MISSING_PDL`.
* The DT trend uses the full stable band; the ambiguous zone between the stable
  band and the worsening threshold reads ``unknown``, never ``stable``.
* Classification is **terminal-anchored**: an earlier plateau→recovery→plateau
  cycle is not called ``re_arrest`` unless the series actually *ends* arrested;
  a terminal sustained growth wins over historical crisis.
* Sparse passage sampling (large absolute gaps) is flagged; downstream, that
  blocks a PDL-derived status override rather than trusting an absolute PDL gain.
* A recent-window signal (``terminal_dt_deterioration``) surfaces terminal DT
  worsening that a whole-series early/late median could dilute.
"""

from __future__ import annotations

import math
from enum import StrEnum
from statistics import median

from pydantic import BaseModel, Field, model_validator

from virtualcell.agents.immortalization.models import MarkerValue, PassageObservation


class TrajectoryThresholds(BaseModel):
    """Policy thresholds for trajectory classification (v1 benchmark, not a law).

    The DT-trend thresholds must stay ordered so the stable band is well-formed:
    ``improving <= 1 - relative`` and ``worsening >= 1 + relative``.
    """

    min_timepoints: int = 3
    stable_dt_relative_change: float = 0.25
    worsening_dt_fold_change: float = 1.50
    improving_dt_fold_change: float = 0.75
    plateau_pdl_gain: float = 1.0
    recovery_min_pdl_gain: float = 2.0
    min_recovery_intervals: int = 2
    # Absolute passage gap beyond which absolute PDL-gain judgments are low-confidence.
    # A policy sampling bound, NOT a per-passage biological constant.
    max_supported_passage_gap: int = 8

    @model_validator(mode="after")
    def _check_threshold_ordering(self) -> TrajectoryThresholds:
        if not 0.0 < self.improving_dt_fold_change <= 1.0:
            raise ValueError("improving_dt_fold_change must be in (0, 1]")
        if self.worsening_dt_fold_change < 1.0:
            raise ValueError("worsening_dt_fold_change must be >= 1")
        if not 0.0 <= self.stable_dt_relative_change < 1.0:
            raise ValueError("stable_dt_relative_change must be in [0, 1)")
        stable_low = 1.0 - self.stable_dt_relative_change
        stable_high = 1.0 + self.stable_dt_relative_change
        if self.improving_dt_fold_change > stable_low:
            raise ValueError("improving threshold must not exceed the stable band's lower bound")
        if self.worsening_dt_fold_change < stable_high:
            raise ValueError(
                "worsening threshold must not fall below the stable band's upper bound"
            )
        if self.min_timepoints < 2:
            raise ValueError("min_timepoints must be >= 2")
        return self


class SeriesQualityFlag(StrEnum):
    """Non-fatal quality concerns about a passage series (kept distinct from errors).

    Every member is actually produced by :func:`extract_trajectory`. (An explicit
    single-point outlier flag was intentionally *not* added: the early/late median
    window already absorbs one-off spikes, and a global median/MAD rule mislabels a
    genuine terminal deterioration *trend* as an outlier. See the benchmark md.)
    """

    INSUFFICIENT_TIMEPOINTS = "insufficient_timepoints"
    IRREGULAR_PASSAGE_INTERVALS = "irregular_passage_intervals"
    NON_MONOTONIC_PDL = "non_monotonic_pdl"
    MISSING_DT = "missing_dt"
    MISSING_PDL = "missing_pdl"
    SPARSE_PASSAGE_SAMPLING = "sparse_passage_sampling"


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
    # Per-axis usable counts: an observation counts toward an axis only if that
    # axis was actually measured. Downstream gating reads these, not timepoint_count.
    usable_PDL_timepoints: int = 0
    usable_DT_timepoints: int = 0
    derived_PDL_trend: MarkerValue = MarkerValue.UNKNOWN
    derived_DT_trend: MarkerValue = MarkerValue.UNKNOWN
    early_DT_median: float | None = None
    late_DT_median: float | None = None
    DT_fold_change: float | None = None
    total_PDL_gain: float | None = None
    plateau_interval: tuple[int, int] | None = None
    recovery_interval: tuple[int, int] | None = None
    # Recent DT window worsened sharply vs the preceding window; surfaced as an
    # uncertainty even when the whole-series trend does not (yet) read worsening.
    terminal_dt_deterioration: bool = False
    quality_flags: list[SeriesQualityFlag] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


# --- Deterministic extraction engine ----------------------------------------
#
# All judgment is threshold-driven (TrajectoryThresholds). Classification is
# structural and terminal-anchored: consecutive PDL observations are labelled
# "growing" or "flat", runs of like labels are compressed, and a crisis/recovery
# history is only allowed to name the state when the series *ends* in that state.


def _window(n: int) -> int:
    """Size of the early/late median window: ~1/3 of the points, so a single
    outlier cannot flip the DT trend (>=1 for any non-empty series)."""
    return max(1, math.ceil(n / 3))


def _dt_trend(fold: float | None, t: TrajectoryThresholds) -> MarkerValue:
    """Map a late/early DT fold change to a trend, using the full stable band.

    The zone between the stable band's upper bound and the worsening threshold is
    genuinely ambiguous and reads ``unknown`` — it is never rounded down to stable.
    """
    if fold is None:
        return MarkerValue.UNKNOWN
    if fold <= t.improving_dt_fold_change:
        return MarkerValue.IMPROVED
    if abs(fold - 1.0) <= t.stable_dt_relative_change:
        return MarkerValue.STABLE
    if fold >= t.worsening_dt_fold_change:
        return MarkerValue.WORSENING
    return MarkerValue.UNKNOWN


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
    features per axis, and classifies the proliferation course. Insufficient or
    missing axes degrade gracefully to quality flags rather than raising.
    """
    t = thresholds or TrajectoryThresholds()
    ordered = sorted(observations, key=lambda o: o.passage)
    n = len(ordered)
    flags: list[SeriesQualityFlag] = []
    rationale: list[str] = []

    first_passage = ordered[0].passage if ordered else None
    last_passage = ordered[-1].passage if ordered else None

    # Passage-cadence quality: irregular (uneven) spacing is a general warning over
    # all observations. Sparse *PDL* sampling is judged per axis below (a large gap
    # between the PDL-carrying passages is what makes an absolute PDL-gain judgment
    # low-confidence), so a dense DT axis cannot mask a sparsely-sampled PDL series.
    passages = [o.passage for o in ordered]
    deltas = [b - a for a, b in zip(passages, passages[1:], strict=False)]
    if deltas and max(deltas) > 1.5 * min(deltas):
        flags.append(SeriesQualityFlag.IRREGULAR_PASSAGE_INTERVALS)

    # DT features (median-smoothed early vs late). Usable = observations that
    # actually carry a DT; a trend needs >= min_timepoints usable DT points.
    dt = [(o.passage, o.DT_hours) for o in ordered if o.DT_hours is not None]
    usable_dt = len(dt)
    if usable_dt < n:
        flags.append(SeriesQualityFlag.MISSING_DT)
    early_dt = late_dt = fold = None
    if usable_dt >= t.min_timepoints:
        w = _window(usable_dt)
        early_dt = median([v for _, v in dt[:w]])
        late_dt = median([v for _, v in dt[-w:]])
        fold = late_dt / early_dt
    dt_trend = _dt_trend(fold, t)

    # Recent-window deterioration: the last DT vs the median of the preceding DTs.
    # Needs a real preceding window (>= min_timepoints preceding points) so it only
    # fires on longer series, where a whole-series median could dilute a late spike.
    terminal_det = False
    if usable_dt >= t.min_timepoints + 1:
        preceding = [v for _, v in dt[:-1]]
        prec_median = median(preceding)
        if prec_median > 0 and dt[-1][1] >= t.worsening_dt_fold_change * prec_median:
            terminal_det = True

    # PDL features. Usable = observations that carry a cumulative PDL.
    pdl = [(o.passage, o.cumulative_PDL) for o in ordered if o.cumulative_PDL is not None]
    usable_pdl = len(pdl)
    if usable_pdl < n:
        flags.append(SeriesQualityFlag.MISSING_PDL)
    total_pdl_gain = None
    if usable_pdl >= 2:
        total_pdl_gain = pdl[-1][1] - pdl[0][1]
        pdl_gaps = [b - a for (a, _), (b, _) in zip(pdl, pdl[1:], strict=False)]
        # Sparse PDL sampling: a large gap between PDL-carrying passages makes the
        # absolute PDL-gain judgment low-confidence, regardless of how densely other
        # axes were measured. This is the flag that gates the PDL override downstream.
        if max(pdl_gaps) > t.max_supported_passage_gap:
            flags.append(SeriesQualityFlag.SPARSE_PASSAGE_SAMPLING)
        if any(b < a for (_, a), (_, b) in zip(pdl, pdl[1:], strict=False)):
            flags.append(SeriesQualityFlag.NON_MONOTONIC_PDL)

    base = {
        "first_passage": first_passage,
        "last_passage": last_passage,
        "timepoint_count": n,
        "usable_PDL_timepoints": usable_pdl,
        "usable_DT_timepoints": usable_dt,
        "early_DT_median": early_dt,
        "late_DT_median": late_dt,
        "DT_fold_change": round(fold, 2) if fold is not None else None,
        "total_PDL_gain": round(total_pdl_gain, 3) if total_pdl_gain is not None else None,
        "derived_DT_trend": dt_trend,
        "terminal_dt_deterioration": terminal_det,
        "quality_flags": flags,
    }

    # State classification is a PDL-axis judgment: it needs enough *usable PDL*
    # points, independent of how many DT points exist.
    if usable_pdl < t.min_timepoints:
        flags.append(SeriesQualityFlag.INSUFFICIENT_TIMEPOINTS)
        rationale.append(
            f"Only {usable_pdl} usable PDL timepoint(s); "
            f">= {t.min_timepoints} needed to classify a trajectory."
        )
        return TrajectoryAssessment(
            state=TrajectoryState.INSUFFICIENT_SERIES, rationale=rationale, **base
        )

    pdl_passages = [p for p, _ in pdl]
    gains = [b - a for (_, a), (_, b) in zip(pdl, pdl[1:], strict=False)]
    labels = ["G" if g >= t.plateau_pdl_gain else "F" for g in gains]
    runs = _runs(labels)
    last_label = labels[-1]
    base["derived_PDL_trend"] = MarkerValue.INCREASING if last_label == "G" else MarkerValue.PLATEAU

    flat_before_terminal = len([r for r in runs if r[0] == "F"]) >= 2 or (
        len(runs) >= 3 and runs[0][0] == "G"
    )

    # --- Terminal arrest (series ends flat) ---------------------------------
    if last_label == "F":
        terminal_flat = runs[-1]
        growth_runs = [r for r in runs if r[0] == "G"]
        # Re-arrest only when growth actually recovered after an earlier plateau and
        # the series then arrested again — i.e. the terminal run is flat AND some
        # flat run precedes the last growth run. Terminal state wins over history.
        if growth_runs:
            last_g = growth_runs[-1]
            if any(r[0] == "F" and r[2] < last_g[1] for r in runs):
                rationale.append(
                    "Grew after an earlier plateau, then arrested again; classified by "
                    "the terminal (arrested) state, not the intervening recovery."
                )
                return TrajectoryAssessment(
                    state=TrajectoryState.RE_ARREST,
                    recovery_interval=_span(pdl_passages, last_g[1], last_g[2]),
                    plateau_interval=_span(pdl_passages, terminal_flat[1], terminal_flat[2]),
                    rationale=rationale,
                    **base,
                )
        # Plain terminal plateau — unless DT is improving against a stalled PDL.
        if dt_trend == MarkerValue.IMPROVED:
            rationale.append(
                "PDL has stalled while the doubling time improves; directions disagree."
            )
            return TrajectoryAssessment(
                state=TrajectoryState.CONFLICTING_TRAJECTORY, rationale=rationale, **base
            )
        rationale.append("Population doublings have essentially stopped.")
        return TrajectoryAssessment(
            state=TrajectoryState.PLATEAU,
            plateau_interval=_span(pdl_passages, terminal_flat[1], terminal_flat[2]),
            rationale=rationale,
            **base,
        )

    # --- Terminal growth (series ends growing) ------------------------------
    last_run = runs[-1]
    if any(r[0] == "F" for r in runs[:-1]):
        # Recovery: a final growth run preceded by a plateau.
        recovery_len = last_run[2] - last_run[1] + 1
        recovery_gain = sum(gains[last_run[1] : last_run[2] + 1])
        recovery_span = _span(pdl_passages, last_run[1], last_run[2])
        prev_flat = [r for r in runs[:-1] if r[0] == "F"][-1]
        plateau_span = _span(pdl_passages, prev_flat[1], prev_flat[2])
        if flat_before_terminal:
            rationale.append(
                "Series shows an earlier plateau/recovery cycle; the current terminal "
                "run is sustained growth."
            )
        if recovery_len >= t.min_recovery_intervals and recovery_gain >= t.recovery_min_pdl_gain:
            rationale.append("Plateau followed by sustained recovery over multiple intervals.")
            return TrajectoryAssessment(
                state=TrajectoryState.RECOVERY_AFTER_PLATEAU,
                plateau_interval=plateau_span,
                recovery_interval=recovery_span,
                rationale=rationale,
                **base,
            )
        rationale.append("Recovery is observed but durability is not yet established.")
        return TrajectoryAssessment(
            state=TrajectoryState.TRANSIENT_RECOVERY,
            plateau_interval=plateau_span,
            recovery_interval=recovery_span,
            rationale=rationale,
            **base,
        )

    # Pure growth to the end, no plateau-recovery structure.
    if dt_trend == MarkerValue.WORSENING:
        rationale.append("PDL keeps rising but the doubling time progressively worsens.")
        return TrajectoryAssessment(
            state=TrajectoryState.PROGRESSIVE_SLOWDOWN, rationale=rationale, **base
        )
    if dt_trend in (MarkerValue.STABLE, MarkerValue.IMPROVED):
        rationale.append("PDL increases with a stable or improving doubling time.")
        return TrajectoryAssessment(
            state=TrajectoryState.STABLE_GROWTH, rationale=rationale, **base
        )
    # DT unknown/ambiguous: report growth honestly without asserting DT stability.
    rationale.append("PDL increases, but doubling-time stability is unverified.")
    return TrajectoryAssessment(state=TrajectoryState.STABLE_GROWTH, rationale=rationale, **base)
