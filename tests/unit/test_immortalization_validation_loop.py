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


def test_a_measured_retention_loss_changes_what_to_do_next() -> None:
    """`lost` and `retained` currently return identical plans. If measuring an axis cannot
    change the next action, the measurement was decorative."""
    lost = _report(adipogenic_retention=RetentionValue.LOST)
    retained = _report(adipogenic_retention=RetentionValue.RETAINED)
    assert lost.next_experiment != retained.next_experiment


def test_unmeasured_retention_surfaces_as_a_validation_gap() -> None:
    """Silence about an unmeasured axis reads as "nothing to check here". Differentiation
    capacity is exactly the axis a cultured-meat programme cannot skip."""
    unknown = _report(adipogenic_retention=RetentionValue.UNKNOWN)
    guidance = " ".join([*unknown.recommended_validation, *unknown.next_experiment]).lower()
    assert "differentiation" in guidance


def test_unmeasured_retention_is_not_treated_as_retained() -> None:
    unknown = _report(adipogenic_retention=RetentionValue.UNKNOWN)
    retained = _report(adipogenic_retention=RetentionValue.RETAINED)
    assert unknown.recommended_validation != retained.recommended_validation


# --- gap B: genomic stability cannot be stated at all -------------------------


def test_genomic_stability_is_a_typed_input_axis() -> None:
    assert "genomic_stability" in ImmortalizationAssessmentInput.model_fields


def test_an_unrecognised_measurement_key_is_preserved_and_silently_unconsumed() -> None:
    """A recorded finding, not a desired contract — see `docs/immortalization_validation_axes.md`.

    The typed axis fixes the case that mattered, but the generic escape hatch is unchanged:
    a key the vertical does not recognise is accepted, echoed back in `derived_input`, and
    reaches no reasoning, with nothing in the response telling the caller which of their
    measurements were used. Pinned here so that whoever fixes measurement-consumption
    transparency has to come to this test and delete it deliberately.
    """
    unknown_key = _report(measurements={"telomere_length_kb": "4.2"})
    assert unknown_key.model_dump() == _report().model_dump()  # byte-identical: no trace at all


def test_unverified_genomic_stability_is_surfaced_by_the_assessment() -> None:
    """The mechanism path demands genomic stability in its very first recommendation. The
    assessment path never mentions it, so the two halves of the vertical disagree."""
    guidance = " ".join([*_report().recommended_validation, *_report().next_experiment]).lower()
    assert "genomic" in guidance or "karyotype" in guidance


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
