"""Immortalization assessment (cell-engineering vertical).

v0 ships the deterministic rule-based baseline (:func:`baseline_status`) that the
LLM-backed agent will be checked against. The full `ImmortalizationAssessmentAgent`
and `DecisionReport` output land in later PRs; see
``tests/benchmarks/immortalization_v0.md``.
"""

from __future__ import annotations

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.agents.immortalization.baseline import (
    AssessmentFlag,
    CandidateStatus,
    baseline_status,
)
from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ConstructType,
    ImmortalizationAssessmentInput,
    MarkerValue,
    PassageObservation,
    RetentionValue,
)
from virtualcell.agents.immortalization.trajectory import (
    SeriesQualityFlag,
    TrajectoryAssessment,
    TrajectoryState,
    TrajectoryThresholds,
    extract_trajectory,
)

__all__ = [
    "AssessmentFlag",
    "AssessmentIntent",
    "CandidateStatus",
    "ConstructType",
    "ImmortalizationAssessmentAgent",
    "ImmortalizationAssessmentInput",
    "MarkerValue",
    "PassageObservation",
    "RetentionValue",
    "SeriesQualityFlag",
    "TrajectoryAssessment",
    "TrajectoryState",
    "TrajectoryThresholds",
    "baseline_status",
    "extract_trajectory",
    "input_from_scenario",
]
