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

from enum import StrEnum

from pydantic import BaseModel, Field

from virtualcell.agents.immortalization.models import MarkerValue


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
