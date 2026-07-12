"""Tests for the deterministic DecisionReport builder (PR5a).

Runs the benchmark's assessment questions (Q1-Q4, Q7, Q8, Q10) through the builder
and checks the acceptance criteria. Mechanism/hypothesis questions are out of scope
and must be rejected, not silently mis-judged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from virtualcell.agents.immortalization.models import (
    ASSESSMENT_INTENTS,
    ImmortalizationAssessmentInput,
)
from virtualcell.agents.immortalization.rules import (
    UnsupportedIntentError,
    build_decision_report,
)
from virtualcell.reasoning.decision import AssessmentFlag

_SPEC = yaml.safe_load(
    (Path(__file__).parent.parent / "benchmarks" / "immortalization_v0.yaml").read_text(
        encoding="utf-8"
    )
)
_QUESTIONS = _SPEC["questions"]
_MARKER_FIELDS = {
    "PDL_trend",
    "DT_trend",
    "gammaH2AX",
    "SA_b_gal",
    "p16",
    "p21",
    "adipogenic_retention",
}
_ASSESSMENT_VALUES = {intent.value for intent in ASSESSMENT_INTENTS}
_ASSESSMENT_QS = [q for q in _QUESTIONS if q["intent"] in _ASSESSMENT_VALUES]


def _input_from_question(q: dict) -> ImmortalizationAssessmentInput:
    scenario = q["scenario"]
    markers = {k: scenario[k] for k in _MARKER_FIELDS if k in scenario}
    extras = {
        k: v
        for k, v in scenario.items()
        if k not in _MARKER_FIELDS and k not in ("species", "cell_type")
    }
    return ImmortalizationAssessmentInput(
        intent=q["intent"],
        species=scenario.get("species"),
        cell_type=scenario.get("cell_type"),
        measurements=extras,
        **markers,
    )


def _by_id(qid: str):
    q = next(q for q in _QUESTIONS if q["id"] == qid)
    return build_decision_report(_input_from_question(q))


def test_scope_covers_the_expected_seven_questions() -> None:
    assert {q["id"] for q in _ASSESSMENT_QS} == {
        "IMM-Q1",
        "IMM-Q2",
        "IMM-Q3",
        "IMM-Q4",
        "IMM-Q7",
        "IMM-Q8",
        "IMM-Q10",
    }


@pytest.mark.parametrize("q", _ASSESSMENT_QS, ids=[q["id"] for q in _ASSESSMENT_QS])
def test_builder_status_and_flags_match_benchmark(q: dict) -> None:
    report = build_decision_report(_input_from_question(q))

    acceptable = q.get("acceptable_status")
    if acceptable:
        assert report.candidate_status in acceptable, f"{q['id']}: {report.candidate_status}"
    else:
        assert report.candidate_status == q["expected_status"], f"{q['id']}"
    if "expected_flags" in q:
        assert sorted(report.flags) == sorted(q["expected_flags"]), f"{q['id']}: {report.flags}"

    # Relevance scores must stay None (no scoring formula yet).
    assert report.cell_type_relevance is None
    assert report.species_relevance is None
    assert report.actionability is None


def test_possible_candidate_is_not_stated_as_confirmed() -> None:
    report = _by_id("IMM-Q2")
    assert report.candidate_status == "possible_candidate"
    text = report.conclusion.lower()
    assert "not confirmed immortalization" in text
    assert "confirmed immortalized" not in text
    assert "definitively immortal" not in text


def test_q7_separates_functionality_from_candidacy() -> None:
    report = _by_id("IMM-Q7")
    assert AssessmentFlag.FUNCTIONALITY_COMPROMISED in report.flags
    assert any("differentiation" in risk.lower() for risk in report.overinterpretation_risk)


def test_q8_reports_missing_axes() -> None:
    report = _by_id("IMM-Q8")
    assert report.candidate_status == "insufficient_evidence"
    assert set(report.missing_axes) >= {"gammaH2AX", "SA-b-Gal", "p16", "p21"}


def test_q10_reports_both_sides_and_conflict() -> None:
    report = _by_id("IMM-Q10")
    assert report.supporting_evidence and report.contradicting_evidence
    assert report.conflict_explanation


def test_conflict_explanation_requires_actual_conflict() -> None:
    # A conflicting intent with no measured markers must NOT fabricate a conflict.
    empty = ImmortalizationAssessmentInput(intent="conflicting_evidence_assessment")
    assert build_decision_report(empty).conflict_explanation == []


def test_mechanism_intent_is_rejected_explicitly() -> None:
    q5 = next(q for q in _QUESTIONS if q["id"] == "IMM-Q5")
    with pytest.raises(UnsupportedIntentError):
        build_decision_report(_input_from_question(q5))


# --- PR7c: time-series integration -------------------------------------------


def _series_input(observations: list[dict], **snapshot) -> ImmortalizationAssessmentInput:
    return ImmortalizationAssessmentInput(
        intent="immortalization_assessment", observations=observations, **snapshot
    )


def test_snapshot_only_input_is_unchanged_by_pr7() -> None:
    # No observations => no trajectory, no derived overrides, empty conflicts:
    # a v0 snapshot report is byte-for-byte the prior behavior.
    data = ImmortalizationAssessmentInput(
        intent="immortalization_assessment", PDL_trend="plateau", DT_trend="worsening"
    )
    report = build_decision_report(data)
    assert report.trajectory is None
    assert report.derived_input == {}
    assert report.input_conflicts == []
    assert report.candidate_status == "senescence_or_stress_prone"


def test_derived_trend_drives_status_from_raw_series() -> None:
    # Raw DT 42->80->100 with rising PDL, NO snapshot trend supplied: the platform
    # must derive worsening from the series and land senescence_or_stress_prone.
    report = build_decision_report(
        _series_input(
            [
                {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 42},
                {"passage": 30, "cumulative_PDL": 25.5, "DT_hours": 80},
                {"passage": 35, "cumulative_PDL": 27.0, "DT_hours": 100},
            ]
        )
    )
    assert report.trajectory["state"] == "progressive_slowdown"
    assert report.derived_input["DT_trend"] == "worsening"
    assert report.candidate_status == "senescence_or_stress_prone"
    assert AssessmentFlag.TREND_NEEDED in report.flags


def test_snapshot_series_conflict_is_surfaced_not_silent() -> None:
    # User asserts DT_trend=stable; the raw series says worsening. The series wins,
    # and the disagreement is reported explicitly.
    report = build_decision_report(
        _series_input(
            [
                {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 42},
                {"passage": 30, "cumulative_PDL": 25.5, "DT_hours": 80},
                {"passage": 35, "cumulative_PDL": 27.0, "DT_hours": 100},
            ],
            DT_trend="stable",
            PDL_trend="increasing",
        )
    )
    assert report.input_conflicts
    assert "worsening" in report.input_conflicts[0]
    assert report.candidate_status == "senescence_or_stress_prone"


def test_trajectory_is_separate_from_candidate_status() -> None:
    # A durable recovery is a proliferation course, not a candidacy verdict: with
    # no senescence axis measured, the status stays insufficient_evidence.
    report = build_decision_report(
        _series_input(
            [
                {"passage": 20, "cumulative_PDL": 20.0, "DT_hours": 40},
                {"passage": 25, "cumulative_PDL": 20.3, "DT_hours": 78},
                {"passage": 30, "cumulative_PDL": 23.0, "DT_hours": 44},
                {"passage": 35, "cumulative_PDL": 26.0, "DT_hours": 38},
            ]
        )
    )
    assert report.trajectory["state"] == "recovery_after_plateau"
    assert report.candidate_status == "insufficient_evidence"


def test_transient_recovery_flags_durability_uncertainty() -> None:
    report = build_decision_report(
        _series_input(
            [
                {"passage": 20, "cumulative_PDL": 18.0, "DT_hours": 34},
                {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 36},
                {"passage": 30, "cumulative_PDL": 22.4, "DT_hours": 70},
                {"passage": 35, "cumulative_PDL": 25.0, "DT_hours": 40},
            ]
        )
    )
    assert report.trajectory["state"] == "transient_recovery"
    assert any("durability" in u.lower() for u in report.uncertainty)
