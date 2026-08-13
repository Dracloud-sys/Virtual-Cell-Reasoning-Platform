"""The recommend → measure → interpret loop, and where it was open.

The vertical tells a researcher to verify genomic stability and differentiation capacity.
Until PR16 it could not read the answer back: measure the thing it asked for, hand the
result in, and the report was byte-identical to never having measured it. A platform that
asks for evidence it cannot consume is asking rhetorically.

Written gap-first. Every test that documents a defect is marked ``xfail(strict=True)`` in the
characterization commit, so it fails loudly the moment the loop closes and must be un-marked
deliberately rather than drifting into a permanent contract for the broken behaviour. The
unmarked tests state what was *already* right and must survive the fix — chiefly that neither
axis is allowed to move the candidate status.
"""

from __future__ import annotations

import pytest

from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ImmortalizationAssessmentInput,
    MarkerValue,
    RetentionValue,
)
from virtualcell.agents.immortalization.rules import build_decision_report
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import CandidateStatus

# A culture that reaches `possible_candidate` on its own, so anything that moves below is
# attributable to the validation axis under test and not to the proliferation call.
CANDIDATE = {
    "intent": AssessmentIntent.IMMORTALIZATION_ASSESSMENT,
    "species": "bovine",
    "cell_type": "fibroblast",
    "PDL_trend": MarkerValue.INCREASING,
    "DT_trend": MarkerValue.STABLE,
    "gammaH2AX": MarkerValue.LOW,
    "SA_b_gal": MarkerValue.LOW,
    "p16": MarkerValue.LOW,
    "p21": MarkerValue.LOW,
}


def _report(**overrides):
    return build_decision_report(ImmortalizationAssessmentInput(**{**CANDIDATE, **overrides}))


# --- what was already right, and must stay right ------------------------------


@pytest.mark.parametrize("retention", list(RetentionValue))
def test_differentiation_retention_never_moves_the_candidate_status(retention) -> None:
    """Immortalization is not utility. A line can proliferate indefinitely and be useless,
    and collapsing those into one verdict would lose the more actionable half."""
    assert _report(adipogenic_retention=retention).candidate_status is (
        CandidateStatus.POSSIBLE_CANDIDATE
    )


def test_lost_retention_is_reported_as_a_flag_and_as_evidence() -> None:
    report = _report(adipogenic_retention=RetentionValue.LOST)
    assert "functionality_compromised" in [f.value for f in report.flags]
    assert any(
        "differentiation capacity is lost" in c.statement.lower()
        for c in report.contradicting_evidence
    )


def test_retained_retention_raises_no_functionality_flag() -> None:
    report = _report(adipogenic_retention=RetentionValue.RETAINED)
    assert "functionality_compromised" not in [f.value for f in report.flags]


# --- gap A: the retention axis answers, and nothing downstream changes --------


@pytest.mark.xfail(strict=True, reason="PR16 gap: retention outcome does not change the plan")
def test_a_measured_retention_loss_changes_what_to_do_next() -> None:
    """`lost` and `retained` currently return identical plans. If measuring an axis cannot
    change the next action, the measurement was decorative."""
    lost = _report(adipogenic_retention=RetentionValue.LOST)
    retained = _report(adipogenic_retention=RetentionValue.RETAINED)
    assert lost.next_experiment != retained.next_experiment


@pytest.mark.xfail(strict=True, reason="PR16 gap: unverified functionality is never surfaced")
def test_unmeasured_retention_surfaces_as_a_validation_gap() -> None:
    """Silence about an unmeasured axis reads as "nothing to check here". Differentiation
    capacity is exactly the axis a cultured-meat programme cannot skip."""
    unknown = _report(adipogenic_retention=RetentionValue.UNKNOWN)
    guidance = " ".join([*unknown.recommended_validation, *unknown.next_experiment]).lower()
    assert "differentiation" in guidance


@pytest.mark.xfail(strict=True, reason="PR16 gap: unknown is indistinguishable from retained")
def test_unmeasured_retention_is_not_treated_as_retained() -> None:
    unknown = _report(adipogenic_retention=RetentionValue.UNKNOWN)
    retained = _report(adipogenic_retention=RetentionValue.RETAINED)
    assert unknown.recommended_validation != retained.recommended_validation


# --- gap B: genomic stability cannot be stated at all -------------------------


@pytest.mark.xfail(strict=True, reason="PR16 gap: no typed genomic-stability axis")
def test_genomic_stability_is_a_typed_input_axis() -> None:
    assert "genomic_stability" in ImmortalizationAssessmentInput.model_fields


@pytest.mark.xfail(strict=True, reason="PR16 gap: generic measurements are never consumed")
def test_a_genomic_stability_result_handed_in_generically_reaches_the_reasoning() -> None:
    """The user-facing symptom: an abnormal karyotype is accepted, echoed back in
    `derived_input`, and changes nothing — no flag, no evidence, no risk, no plan change."""
    silent = _report(measurements={"karyotype": "abnormal", "genomic_stability": "lost"})
    baseline = _report()
    assert (silent.flags, silent.contradicting_evidence, silent.overinterpretation_risk) != (
        baseline.flags,
        baseline.contradicting_evidence,
        baseline.overinterpretation_risk,
    )


@pytest.mark.xfail(strict=True, reason="PR16 gap: genomic stability is never asked for")
def test_unverified_genomic_stability_is_surfaced_by_the_assessment() -> None:
    """The mechanism path demands genomic stability in its very first recommendation. The
    assessment path never mentions it, so the two halves of the vertical disagree."""
    guidance = " ".join([*_report().recommended_validation, *_report().next_experiment]).lower()
    assert "genomic" in guidance or "karyotype" in guidance


@pytest.mark.xfail(strict=True, reason="PR16 gap: no observation path into genomic instability")
def test_the_graph_can_reach_genomic_instability_from_a_readout() -> None:
    """`phenotype:genomic_instability` exists as a node with nothing pointing into it: it is
    reachable only as a *next test* to run, never as a state that was observed."""
    source = ImmortalizationSeedSource()
    indicating = {
        edge.source_id
        for edge in source.interactions()
        if edge.target_id == "phenotype:genomic_instability" and edge.relation == "indicates"
    }
    assert indicating
