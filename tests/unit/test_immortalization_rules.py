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


# --- PR7 hardening: quality gating at the report level ------------------------


def test_non_monotonic_pdl_does_not_flip_status_and_is_surfaced() -> None:
    # A corrupt (non-monotonic) PDL series must NOT override the snapshot plateau
    # into increasing; the snapshot judgment stands and the block is reported.
    report = build_decision_report(
        _series_input(
            [
                {"passage": 20, "cumulative_PDL": 25.0, "DT_hours": 40},
                {"passage": 25, "cumulative_PDL": 24.0, "DT_hours": 42},  # PDL drops
                {"passage": 30, "cumulative_PDL": 26.0, "DT_hours": 41},
            ],
            PDL_trend="plateau",
        )
    )
    assert "non_monotonic_pdl" in report.trajectory["quality_flags"]
    assert "PDL_trend" not in report.derived_input  # override withheld
    assert report.blocked_overrides
    assert report.candidate_status == "senescence_or_stress_prone"  # snapshot plateau kept


def test_sparse_series_does_not_override_status() -> None:
    report = build_decision_report(
        _series_input(
            [
                {"passage": 1, "cumulative_PDL": 1.0, "DT_hours": 40},
                {"passage": 10, "cumulative_PDL": 1.8, "DT_hours": 41},
                {"passage": 20, "cumulative_PDL": 2.6, "DT_hours": 42},
            ],
            PDL_trend="increasing",
        )
    )
    assert "sparse_passage_sampling" in report.trajectory["quality_flags"]
    assert "PDL_trend" not in report.derived_input
    assert any("sparse" in b.lower() for b in report.blocked_overrides)


def test_insufficient_pdl_does_not_block_a_valid_dt_trend() -> None:
    # usable PDL = 2, usable DT = 3: the DT axis is fully sampled and worsening, so
    # it must drive the assessment even though PDL is too thin for a trajectory.
    report = build_decision_report(
        _series_input(
            [
                {"passage": 1, "cumulative_PDL": 1.0, "DT_hours": 30},
                {"passage": 2, "DT_hours": 60},
                {"passage": 3, "cumulative_PDL": 3.0, "DT_hours": 90},
            ],
            PDL_trend="increasing",
            DT_trend="stable",
        )
    )
    assert report.trajectory["state"] == "insufficient_series"  # PDL-axis verdict
    assert report.derived_input.get("DT_trend") == "worsening"  # DT still applied
    assert "PDL_trend" not in report.derived_input  # PDL snapshot kept
    assert report.candidate_status == "senescence_or_stress_prone"


def test_insufficient_dt_does_not_block_a_valid_pdl_trend() -> None:
    # usable DT = 2, usable PDL = 3: PDL trend applies; DT stays the snapshot value
    # and is not asserted as verified.
    report = build_decision_report(
        _series_input(
            [
                {"passage": 1, "cumulative_PDL": 1.0, "DT_hours": 30},
                {"passage": 2, "cumulative_PDL": 2.0},
                {"passage": 3, "cumulative_PDL": 3.0, "DT_hours": 60},
            ],
            DT_trend="stable",
        )
    )
    assert report.derived_input.get("PDL_trend") == "increasing"
    assert "DT_trend" not in report.derived_input  # DT underdetermined, snapshot kept


def test_sparse_pdl_blocks_pdl_only_dt_still_applies() -> None:
    # PDL sampled sparsely (blocked) while DT is dense and worsening (applied).
    obs = [
        {
            "passage": p,
            "cumulative_PDL": {1: 1.0, 15: 5.0, 30: 9.0}.get(p),
            "DT_hours": 30 + p * 3,
        }
        for p in range(1, 31)
    ]
    report = build_decision_report(_series_input(obs, PDL_trend="plateau", DT_trend="stable"))
    assert "sparse_passage_sampling" in report.trajectory["quality_flags"]
    assert "PDL_trend" not in report.derived_input  # PDL blocked
    assert report.derived_input.get("DT_trend") == "worsening"  # DT applied
    assert any("sparse" in b.lower() for b in report.blocked_overrides)


def test_dt_unknown_pdl_sufficient_applies_pdl_only() -> None:
    report = build_decision_report(
        _series_input(
            [
                {"passage": 1, "cumulative_PDL": 1.0},
                {"passage": 2, "cumulative_PDL": 2.0},
                {"passage": 3, "cumulative_PDL": 3.0},
            ],
            DT_trend="stable",
        )
    )
    assert report.derived_input.get("PDL_trend") == "increasing"
    assert "DT_trend" not in report.derived_input  # DT unknown -> snapshot kept, not verified
    assert "missing_dt" in report.trajectory["quality_flags"]


def test_sparse_pdl_blocks_override_even_with_dense_dt() -> None:
    # PDL sampled sparsely (passages 1/15/30) while DT is dense: the sparse-PDL flag
    # must still block the PDL override so the snapshot judgment is not flipped.
    obs = [
        {"passage": p, "cumulative_PDL": {1: 1.0, 15: 5.0, 30: 9.0}.get(p), "DT_hours": 40}
        for p in range(1, 31)
    ]
    report = build_decision_report(_series_input(obs, PDL_trend="plateau"))
    assert "sparse_passage_sampling" in report.trajectory["quality_flags"]
    assert "PDL_trend" not in report.derived_input
    assert any("sparse" in b.lower() for b in report.blocked_overrides)


def test_terminal_dt_spike_surfaced_in_uncertainty() -> None:
    obs = [{"passage": i + 1, "cumulative_PDL": 1.0 + i, "DT_hours": 40} for i in range(10)] + [
        {"passage": 11, "cumulative_PDL": 11.0, "DT_hours": 400}
    ]
    report = build_decision_report(_series_input(obs))
    assert report.trajectory["terminal_dt_spike"] is True
    assert any("terminal spike" in u.lower() for u in report.uncertainty)


def test_conflict_explanation_names_only_measured_markers() -> None:
    # SA-b-Gal low + p16 high + p21 high: the conflict is driven by low SA-b-Gal,
    # and must NOT cite "normal p16" while p16 is measured high.
    report = build_decision_report(
        ImmortalizationAssessmentInput(
            intent="conflicting_evidence_assessment",
            SA_b_gal="low",
            p16="high",
            p21="high",
        )
    )
    text = " ".join(report.conflict_explanation).lower()
    assert text  # a conflict is reported
    assert "normal p16" not in text
    assert "low sa-b-gal" in text
    # And it does not contradict the contradicting-evidence block.
    contra = " ".join(c.statement.lower() for c in report.contradicting_evidence)
    assert "p16 is elevated" in contra
