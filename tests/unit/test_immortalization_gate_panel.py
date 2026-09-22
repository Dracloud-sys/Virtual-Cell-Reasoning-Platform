"""The positive-call gate must require evidence the field actually produces.

`baseline.py` gated `possible_candidate` on a three-way conjunction that named **γH2AX**
specifically. `tests/benchmarks/literature/` surveyed 50 papers that establish immortalized
lines and found γH2AX in **zero** of them, and all three gate conditions together in zero.
A gate whose positive branch cannot be reached from published characterization data is not
cautious; it is unreachable, and every real case reads `insufficient_evidence` regardless of
how well characterized it was.

The defect was never "the gate asks for senescence evidence". That is right, and it stays.
The defect was **privileging one marker**: the survey's common evidence is passages/PDL
(54%), differentiation (30%), morphology (26%) and karyotype (24%), with SA-β-gal the
senescence stain that is actually run (8%) — and γH2AX nowhere. So the requirement
generalizes from one named axis to *any measured senescence axis reading low*, and an
**unreported** doubling time stops blocking a call while a **worsening** one still does:
silence is not a stress signal, but a lengthening doubling time is.

These questions were written before the change. What they pin: no single senescence marker
is privileged, nothing that used to clear the gate stops clearing it, absence of evidence is
not evidence of stress, and the caution the gate exists for survives intact.
"""

from __future__ import annotations

import pytest

from virtualcell.agents.immortalization.baseline import baseline_status
from virtualcell.reasoning.decision import AssessmentFlag, CandidateStatus

# --- no single marker is privileged --------------------------------------------------------


@pytest.mark.parametrize("axis", ["SA_b_gal", "p16", "p21", "gammaH2AX"])
def test_any_measured_senescence_axis_reading_low_can_clear_the_gate(axis: str) -> None:
    """The heart of it: four axes mean the same thing, and any one of them counts.

    `gammaH2AX` is in the list because the change takes nothing away — a panel that used to
    clear the gate still clears it. The other three are what the field publishes.
    """
    status, _ = baseline_status({"PDL_trend": "increasing", axis: "low"})

    assert status is CandidateStatus.POSSIBLE_CANDIDATE


def test_a_published_panel_reaches_a_candidate_call() -> None:
    """The shape the survey says papers actually report: passages, a senescence stain, a karyotype.

    Sustained population doublings with a negative SA-β-gal and a normal karyotype is the
    commonest way this claim is argued in the literature. It returned `insufficient_evidence`
    because no DNA-damage marker was present.
    """
    status, _ = baseline_status(
        {"PDL_trend": "increasing", "SA_b_gal": "low", "genomic_stability": "stable"}
    )

    assert status is CandidateStatus.POSSIBLE_CANDIDATE


# --- absence of evidence is not evidence of stress -----------------------------------------


def test_an_unreported_doubling_time_does_not_block_a_candidate() -> None:
    """Doubling time appears in 16% of the surveyed abstracts. Silence is not a finding."""
    status, _ = baseline_status({"PDL_trend": "increasing", "SA_b_gal": "low"})

    assert status is CandidateStatus.POSSIBLE_CANDIDATE


def test_a_worsening_doubling_time_still_blocks_and_still_reads_as_stress() -> None:
    """The other half of the same rule. A lengthening doubling time is an affirmative signal.

    This is the case the external evaluation's EXT-3 turned on: 36 passages and a reduced
    SA-β-gal, but a doubling time that lengthens monotonically — and the paper itself
    concluded the cells had not achieved complete immortalization.
    """
    status, flags = baseline_status(
        {"PDL_trend": "increasing", "SA_b_gal": "low", "DT_trend": "worsening"}
    )

    assert status is CandidateStatus.SENESCENCE_OR_STRESS_PRONE
    assert AssessmentFlag.TREND_NEEDED in flags


# --- the caution the gate exists for ------------------------------------------------------


def test_proliferation_alone_is_still_not_enough() -> None:
    """Loosening which marker is required must not become requiring no marker at all.

    Growth with nothing measured about senescence is exactly the case `insufficient_evidence`
    is for, and overcalling it is this vertical's named principal risk.
    """
    status, _ = baseline_status({"PDL_trend": "increasing"})

    assert status is CandidateStatus.INSUFFICIENT_EVIDENCE


def test_a_high_senescence_marker_still_beats_proliferation() -> None:
    status, _ = baseline_status({"PDL_trend": "increasing", "SA_b_gal": "high"})

    assert status is CandidateStatus.SENESCENCE_OR_STRESS_PRONE


def test_one_low_marker_cannot_outvote_markers_that_read_high() -> None:
    """The trap in generalizing which marker counts, pinned where the change lives.

    The first cut of this gate cleared on "some axis reads low", which let a single clean
    reading outvote two that screamed senescence. Benchmark IMM-Q10 — deliberately
    contradictory — caught it, and this restates the rule here so it cannot regress
    silently: clearing means one axis low **and none high**.
    """
    status, _ = baseline_status(
        {
            "PDL_trend": "increasing",
            "gammaH2AX": "high",
            "SA_b_gal": "low",
            "p21": "high",
            "p16": "normal",
        }
    )

    assert status is not CandidateStatus.POSSIBLE_CANDIDATE


def test_a_plateaued_pdl_still_reads_as_stress_whatever_else_is_clean() -> None:
    status, _ = baseline_status({"PDL_trend": "plateau", "SA_b_gal": "low"})

    assert status is CandidateStatus.SENESCENCE_OR_STRESS_PRONE


def test_genomic_instability_still_rides_beside_the_status_not_through_it() -> None:
    """Unchanged, and restated here because the gate edit sits next to it.

    Aneuploidy does not stop cells proliferating, so it flags rather than demotes.
    """
    status, flags = baseline_status(
        {"PDL_trend": "increasing", "SA_b_gal": "low", "genomic_stability": "abnormal"}
    )

    assert status is CandidateStatus.POSSIBLE_CANDIDATE
    assert AssessmentFlag.GENOMIC_INSTABILITY_DETECTED in flags
