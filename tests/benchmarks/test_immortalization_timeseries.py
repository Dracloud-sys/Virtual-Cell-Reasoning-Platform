"""Regression harness for the time-series benchmark (PR7).

PR7a validates the *data contract*: the spec is well-formed, its trajectory
vocabulary matches the enum, and every scenario (raw ``observations`` plus any
snapshot markers) parses into a typed :class:`ImmortalizationAssessmentInput`.
Trajectory-state assertions are added in PR7b once the extraction engine exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.models import ImmortalizationAssessmentInput
from virtualcell.agents.immortalization.trajectory import TrajectoryState

SPEC = yaml.safe_load(
    (Path(__file__).parent / "immortalization_timeseries_v1.yaml").read_text(encoding="utf-8")
)
QUESTIONS = SPEC["questions"]


def test_spec_shape_is_stable() -> None:
    assert SPEC["version"] == 1
    assert SPEC["domain"] == "immortalization_timeseries"
    assert len(QUESTIONS) == 12
    assert {q["id"] for q in QUESTIONS} == {f"TS{n:02d}" for n in range(1, 13)}


def test_trajectory_vocab_matches_enum() -> None:
    assert set(SPEC["trajectory_vocab"]) == {state.value for state in TrajectoryState}


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_expected_trajectory_is_in_vocab(q: dict) -> None:
    assert q["expected_trajectory"] in SPEC["trajectory_vocab"]


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_scenario_parses_into_typed_input(q: dict) -> None:
    """Raw observations + snapshot markers must build a valid typed input."""
    data = input_from_scenario(q["intent"], q["scenario"])
    assert isinstance(data, ImmortalizationAssessmentInput)
    # Observations are routed to the typed field, not swallowed into measurements.
    assert len(data.observations) == len(q["scenario"]["observations"])
    assert "observations" not in data.measurements
    # Passages round-trip in the order given (the extractor sorts a copy, not this).
    assert [o.passage for o in data.observations] == [
        o["passage"] for o in q["scenario"]["observations"]
    ]
