"""Regression harness for the time-series benchmark (PR7).

PR7a validates the *data contract*: the spec is well-formed, its trajectory
vocabulary matches the enum, and every scenario (raw ``observations`` plus any
snapshot markers) parses into a typed :class:`ImmortalizationAssessmentInput`.
PR7b adds the trajectory-state assertions: the deterministic engine must
reproduce every ``expected_trajectory`` (and the derived trends / quality flags
where fixed).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.models import ImmortalizationAssessmentInput
from virtualcell.agents.immortalization.rules import build_decision_report
from virtualcell.agents.immortalization.trajectory import TrajectoryState, extract_trajectory

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


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_extracted_trajectory_matches_expected(q: dict) -> None:
    """The deterministic engine reproduces the benchmark's fixed trajectory."""
    data = input_from_scenario(q["intent"], q["scenario"])
    ta = extract_trajectory(data.observations)

    assert ta.state.value == q["expected_trajectory"], f"{q['id']}: {ta.state.value}"

    if "expected_derived_PDL_trend" in q:
        assert ta.derived_PDL_trend.value == q["expected_derived_PDL_trend"], f"{q['id']}"
    if "expected_derived_DT_trend" in q:
        assert ta.derived_DT_trend.value == q["expected_derived_DT_trend"], f"{q['id']}"
    if "expected_quality_flags" in q:
        assert {f.value for f in ta.quality_flags} >= set(q["expected_quality_flags"]), (
            f"{q['id']}: {ta.quality_flags}"
        )


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_report_integrates_trajectory_and_status(q: dict) -> None:
    """The DecisionReport carries the trajectory and the fixed candidate status.

    Status is reported *alongside* the trajectory, never replaced by it.
    """
    data = input_from_scenario(q["intent"], q["scenario"])
    report = build_decision_report(data)

    # Trajectory is always attached (as a serialized dict) when a series is present.
    assert report.trajectory is not None
    assert report.trajectory["state"] == q["expected_trajectory"]

    if "expected_status" in q:
        assert report.candidate_status == q["expected_status"], f"{q['id']}"
    if "acceptable_status" in q:
        assert report.candidate_status in q["acceptable_status"], f"{q['id']}"
    if "expected_flags" in q:
        assert sorted(f.value for f in report.flags) == sorted(q["expected_flags"]), f"{q['id']}"
    if q.get("expects_input_conflict"):
        assert report.input_conflicts, f"{q['id']}: expected a surfaced snapshot/series conflict"
        assert "DT_trend" in report.derived_input


def test_series_alone_never_confirms_a_candidate() -> None:
    """A healthy trajectory with no senescence axis stays insufficient_evidence:
    sustained proliferation is necessary but not sufficient for candidacy."""
    data = input_from_scenario(
        "immortalization_assessment",
        {
            "observations": [
                {"passage": p, "cumulative_PDL": 20 + i * 4, "DT_hours": 30}
                for i, p in enumerate((20, 25, 30))
            ]
        },
    )
    report = build_decision_report(data)
    assert report.trajectory["state"] == "stable_growth"
    assert report.candidate_status == "insufficient_evidence"


def test_extract_does_not_mutate_input_order() -> None:
    """Sorting happens on a copy — the caller's observation list is untouched."""
    data = input_from_scenario(
        "immortalization_assessment",
        {"observations": [{"passage": 35}, {"passage": 25}, {"passage": 30}]},
    )
    before = [o.passage for o in data.observations]
    extract_trajectory(data.observations)
    assert [o.passage for o in data.observations] == before == [35, 25, 30]
