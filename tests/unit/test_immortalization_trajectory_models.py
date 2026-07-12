"""Tests for the PR7a passage time-series data contract.

Covers ``PassageObservation`` field validation, duplicate-passage rejection on
the assessment input, routing of raw observations to the typed field, and the
``TrajectoryAssessment`` output-model defaults. The extraction engine and its
classification logic are exercised separately (PR7b).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.agents.immortalization.models import (
    ImmortalizationAssessmentInput,
    PassageObservation,
)
from virtualcell.agents.immortalization.trajectory import (
    SeriesQualityFlag,
    TrajectoryAssessment,
    TrajectoryState,
    TrajectoryThresholds,
)


def test_passage_observation_accepts_partial_measurements() -> None:
    # DT-only and PDL-only observations are both valid (partial analysis is allowed).
    dt_only = PassageObservation(passage=10, DT_hours=36.0)
    pdl_only = PassageObservation(passage=10, cumulative_PDL=22.0)
    assert dt_only.cumulative_PDL is None
    assert pdl_only.DT_hours is None


def test_passage_observation_preserves_raw_quantitative_markers() -> None:
    # Raw numeric markers coexist with the normalized enum markers; PR7 does NOT
    # auto-threshold them into high/low.
    obs = PassageObservation(passage=30, gammaH2AX=2.4, endogenous_TERT=0.8, endogenous_CDK4=1.2)
    assert obs.gammaH2AX == 2.4
    assert obs.endogenous_TERT == 0.8
    assert obs.endogenous_CDK4 == 1.2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"passage": -1},  # passage must be >= 0
        {"passage": 5, "DT_hours": 0},  # DT must be > 0
        {"passage": 5, "DT_hours": -10},
        {"passage": 5, "cumulative_PDL": -1},  # PDL must be >= 0
        {"passage": 5, "proliferation_fraction": 1.5},  # fraction in [0, 1]
        {"passage": 5, "viability_fraction": -0.1},
    ],
)
def test_passage_observation_rejects_impossible_values(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        PassageObservation(**kwargs)


def test_input_routes_observations_to_typed_field() -> None:
    data = ImmortalizationAssessmentInput(
        intent="immortalization_assessment",
        observations=[
            {"passage": 25, "DT_hours": 42},
            {"passage": 30, "DT_hours": 80},
        ],
    )
    assert len(data.observations) == 2
    assert all(isinstance(o, PassageObservation) for o in data.observations)
    assert data.observations[0].DT_hours == 42


def test_input_defaults_to_empty_observations() -> None:
    # A v0 snapshot-only input still works with no observations.
    data = ImmortalizationAssessmentInput(intent="immortalization_assessment", PDL_trend="plateau")
    assert data.observations == []


def test_duplicate_passage_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate passage"):
        ImmortalizationAssessmentInput(
            intent="immortalization_assessment",
            observations=[
                {"passage": 30, "DT_hours": 40},
                {"passage": 30, "DT_hours": 80},
            ],
        )


def test_out_of_order_passages_are_preserved_not_sorted() -> None:
    # The input model keeps the given order; sorting is the extractor's job (PR7b).
    data = ImmortalizationAssessmentInput(
        intent="immortalization_assessment",
        observations=[{"passage": 35}, {"passage": 25}, {"passage": 30}],
    )
    assert [o.passage for o in data.observations] == [35, 25, 30]


def test_trajectory_assessment_has_sensible_defaults() -> None:
    ta = TrajectoryAssessment(state=TrajectoryState.INSUFFICIENT_SERIES)
    assert ta.timepoint_count == 0
    assert ta.derived_DT_trend.value == "unknown"
    assert ta.quality_flags == []
    assert ta.DT_fold_change is None
    # Round-trips through JSON like the rest of the report.
    dumped = ta.model_dump(mode="json")
    assert dumped["state"] == "insufficient_series"


def test_trajectory_thresholds_defaults() -> None:
    t = TrajectoryThresholds()
    assert t.min_timepoints == 3
    assert t.worsening_dt_fold_change == 1.50
    assert t.min_recovery_intervals == 2
    assert SeriesQualityFlag.INSUFFICIENT_TIMEPOINTS in set(SeriesQualityFlag)
