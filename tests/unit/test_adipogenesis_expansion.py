"""The axes the expansion added, and the rules that decide what each one is allowed to do.

`test_adipogenesis_semantics.py` pins the four rules that predate the expansion. This file
covers what the expansion introduced: efficiency, viability, morphology, the inhibitory axis,
the induction day, and the two conflict cases. Each test states the *decision* the axis
changes — an axis that changes no decision should not exist, and that was the admission
criterion for all six.
"""

from __future__ import annotations

import pytest

from virtualcell.agents.adipogenesis import (
    AdipogenesisAssessmentInput,
    AdipogenesisFlag,
    DifferentiationStatus,
    assess,
)
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.adipogenesis_seed import AdipogenesisSeedSource
from virtualcell.knowledge.sources.base import load_into

FULL_PANEL = {
    "PPARG": "high",
    "CEBPA": "high",
    "FABP4": "high",
    "ADIPOQ": "high",
    "PLIN1": "high",
}
DEAD_PANEL = {marker: "absent" for marker in FULL_PANEL}


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(AdipogenesisSeedSource(), store)
    return store


def _assess(**markers):
    return assess(AdipogenesisAssessmentInput(**markers), _store())


# --- the late-program axis: measured absence vs no measurement ------------------


def test_an_unmeasured_completion_panel_is_a_gap_not_a_stage() -> None:
    """The distinction the expansion nearly lost.

    Early markers plus lipid with nobody having looked at FABP4/ADIPOQ/PLIN1 is *not*
    "partially differentiated" — that would turn an unopened panel into a finding.
    """
    outcome = _assess(PPARG="high", CEBPA="high", lipid_accumulation="high", induction_day=10)
    assert outcome.status is DifferentiationStatus.DIFFERENTIATING
    assert AdipogenesisFlag.LATE_PROGRAM_ABSENT not in outcome.flags
    assert AdipogenesisFlag.MARKERS_INCOMPLETE in outcome.flags


def test_a_measured_and_negative_completion_panel_is_partial() -> None:
    outcome = _assess(
        PPARG="high",
        CEBPA="high",
        FABP4="absent",
        ADIPOQ="absent",
        PLIN1="absent",
        lipid_accumulation="high",
        induction_day=10,
    )
    assert outcome.status is DifferentiationStatus.PARTIALLY_DIFFERENTIATED
    assert AdipogenesisFlag.LATE_PROGRAM_ABSENT in outcome.flags


# --- the induction day: a modifier, never a requirement ------------------------


def test_a_stated_early_day_makes_absent_completion_markers_expected() -> None:
    early = _assess(
        PPARG="high", CEBPA="high", FABP4="absent", lipid_accumulation="high", induction_day=2
    )
    assert any("expected course" in note for note in early.report.uncertainty)


def test_a_late_day_offers_no_such_excuse() -> None:
    late = _assess(
        PPARG="high", CEBPA="high", FABP4="absent", lipid_accumulation="high", induction_day=14
    )
    assert not any("expected course" in note for note in late.report.uncertainty)


def test_an_unstated_day_does_not_manufacture_doubt() -> None:
    """Silence is not a claim that it is early. Treating it as one would quietly make the
    induction day a required field, and it is optional on purpose."""
    stated = _assess(**DEAD_PANEL, lipid_accumulation="absent", induction_day=14)
    silent = _assess(**DEAD_PANEL, lipid_accumulation="absent")
    assert stated.status is silent.status is DifferentiationStatus.NOT_DIFFERENTIATING


def test_an_early_day_withholds_the_failure_call() -> None:
    outcome = _assess(**DEAD_PANEL, lipid_accumulation="absent", induction_day=1)
    assert outcome.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE


# --- viability: blocks the negative call, not the positive one -----------------


def test_a_dying_culture_cannot_support_a_negative_call() -> None:
    healthy = _assess(**DEAD_PANEL, lipid_accumulation="absent", viability="high", induction_day=10)
    dying = _assess(**DEAD_PANEL, lipid_accumulation="absent", viability="absent", induction_day=10)

    assert healthy.status is DifferentiationStatus.NOT_DIFFERENTIATING
    assert dying.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE
    assert AdipogenesisFlag.VIABILITY_COMPROMISED in dying.flags
    assert dying.report.contradicting_evidence  # says why, rather than only flagging


def test_a_struggling_culture_does_not_erase_a_positive_result() -> None:
    """Asymmetric on purpose: lipid plus the program is evidence of something that happened,
    and poor viability does not un-happen it. It is *absence* that becomes ambiguous."""
    outcome = _assess(**FULL_PANEL, lipid_accumulation="high", viability="absent", induction_day=10)
    assert outcome.status is DifferentiationStatus.DIFFERENTIATING
    assert AdipogenesisFlag.VIABILITY_COMPROMISED in outcome.flags


# --- inhibition: held back is not the same as unresponsive ---------------------


def test_an_inhibitor_alongside_a_started_program_does_not_override_it() -> None:
    """The inhibitor is reported; it does not erase evidence that commitment happened."""
    outcome = _assess(
        PPARG="high",
        CEBPA="high",
        FABP4="absent",
        ADIPOQ="absent",
        PLIN1="absent",
        lipid_accumulation="high",
        WNT_signalling="high",
        induction_day=10,
    )
    assert outcome.status is DifferentiationStatus.PARTIALLY_DIFFERENTIATED
    assert AdipogenesisFlag.INHIBITOR_ACTIVE in outcome.flags


@pytest.mark.parametrize("inhibitor", ["WNT_signalling", "DLK1"])
def test_either_inhibitor_reaches_the_inhibited_call(inhibitor: str) -> None:
    outcome = _assess(
        PPARG="absent", CEBPA="absent", lipid_accumulation="absent", **{inhibitor: "high"}
    )
    assert outcome.status is DifferentiationStatus.DIFFERENTIATION_INHIBITED


# --- conflict: lipid without the program ---------------------------------------


def test_lipid_without_a_measured_program_is_not_a_conflict() -> None:
    """A conflict needs two readings that disagree. One reading and one silence is a gap."""
    outcome = _assess(lipid_accumulation="high")
    assert AdipogenesisFlag.CONFLICTING_EVIDENCE not in outcome.flags


def test_lipid_against_a_measured_negative_program_is_a_conflict() -> None:
    outcome = _assess(PPARG="absent", CEBPA="absent", lipid_accumulation="high", induction_day=8)
    assert outcome.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE
    assert AdipogenesisFlag.CONFLICTING_EVIDENCE in outcome.flags
    explanation = " ".join(outcome.report.conflict_explanation)
    assert "PPARG" in explanation and "medium" in explanation


# --- efficiency and morphology: refine a call, never make one ------------------


def test_low_efficiency_qualifies_a_positive_rather_than_reversing_it() -> None:
    outcome = _assess(
        **FULL_PANEL, lipid_accumulation="high", lipid_efficiency="absent", induction_day=10
    )
    assert outcome.status is DifferentiationStatus.DIFFERENTIATING
    assert any("subpopulation" in c.statement for c in outcome.report.contradicting_evidence)


def test_unmeasured_efficiency_is_carried_as_an_uncertainty() -> None:
    outcome = _assess(**FULL_PANEL, lipid_accumulation="high", induction_day=10)
    assert any("proportion of the culture" in note for note in outcome.report.uncertainty)


def test_morphology_alone_decides_nothing() -> None:
    """A photograph is not an assay. Morphology corroborates a call and cannot produce one."""
    outcome = _assess(morphology="high", induction_day=8)
    assert outcome.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE
    assert not outcome.report.supporting_evidence or all(
        "corroborates" not in c.statement for c in outcome.report.supporting_evidence
    )


def test_morphology_corroborates_once_the_measurements_carry_the_call() -> None:
    outcome = _assess(**FULL_PANEL, lipid_accumulation="high", morphology="high", induction_day=10)
    assert any("corroborates" in c.statement for c in outcome.report.supporting_evidence)


# --- the next-experiment list is a plan, not a menu ----------------------------


def test_blocking_experiments_come_before_refining_ones() -> None:
    """A dying culture with an unmeasured panel: repeat on a healthy culture first, then
    the panel. Proposing the refinements first would waste the run that follows."""
    outcome = _assess(PPARG="high", viability="absent", lipid_accumulation="unknown")
    steps = outcome.report.next_experiment
    assert steps[0].startswith("Viability assay")
    assert any("Oil Red O" in step for step in steps)
    assert steps.index("Morphological scoring of lipid-droplet-bearing cells") == len(steps) - 1


def test_no_experiment_is_proposed_twice() -> None:
    outcome = _assess(PPARG="absent", CEBPA="absent", lipid_accumulation="high", viability="absent")
    assert len(outcome.report.next_experiment) == len(set(outcome.report.next_experiment))


# --- maturity stays unverified -------------------------------------------------


def test_a_complete_positive_panel_still_reports_maturity_as_unverified() -> None:
    """ADIPOQ and PLIN1 high is the closest this vertical gets to maturity, and it is not
    close. Suppressing the caveat here would say marker positivity verifies maturity."""
    outcome = _assess(**FULL_PANEL, lipid_accumulation="high", induction_day=14)
    assert AdipogenesisFlag.MATURATION_UNVERIFIED in outcome.flags
    assert any(
        "functional characterisation" in goal for goal in outcome.report.recommended_validation
    )


def test_the_caveat_is_not_attached_to_calls_it_says_nothing_about() -> None:
    outcome = _assess(**DEAD_PANEL, lipid_accumulation="absent", induction_day=10)
    assert outcome.status is DifferentiationStatus.NOT_DIFFERENTIATING
    assert AdipogenesisFlag.MATURATION_UNVERIFIED not in outcome.flags
