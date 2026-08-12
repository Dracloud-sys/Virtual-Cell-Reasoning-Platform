"""Characterization of the two decision assemblies, before PR14b extracts anything.

These tests pin what `docs/pr14b_assembly_comparison.md` found by reading the two builders
side by side. They exist so the extraction has something to be checked *against*: a shared
primitive that changes any of these has changed behaviour, whatever its docstring says.

They are characterization tests, not aspirations. Where they pin something the comparison
called a defect — the first vertical's status vocabulary sitting in the shared contract — the
test asserts *the consequence a second domain lives with*, not the mechanism, so PR14b can fix
the mechanism without rewriting the test into a different claim.
"""

from __future__ import annotations

import pytest

from virtualcell.agents.adipogenesis import (
    AdipogenesisAssessmentInput,
    DifferentiationStatus,
    assess,
)
from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.rules import build_decision_report
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import seed_registered_domains
from virtualcell.reasoning.decision import CandidateStatus, DecisionReport
from virtualcell.reasoning.kernel import INTERPRETATION_CONFIDENCE, MEASUREMENT_CONFIDENCE


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    return store


def _immortalization(**scenario) -> DecisionReport:
    return build_decision_report(input_from_scenario("immortalization_assessment", scenario))


def _adipogenesis(**markers):
    return assess(AdipogenesisAssessmentInput(**markers), _store())


IMMO_RICH = {"PDL_trend": "increasing", "DT_trend": "worsening", "gammaH2AX": "high"}
ADIPO_RICH = {"PPARG": "high", "CEBPA": "high"}


# --- shared behaviour: what both assemblies genuinely do ---------------------


def test_both_report_evidence_on_both_sides() -> None:
    """A report that can only argue one way is not a decision report."""
    immo = _immortalization(**IMMO_RICH)
    adipo = _adipogenesis(**ADIPO_RICH).report
    for report in (immo, adipo):
        assert report.supporting_evidence or report.contradicting_evidence
        assert isinstance(report.supporting_evidence, list)
        assert isinstance(report.contradicting_evidence, list)


def test_both_follow_the_kernel_tier_conventions() -> None:
    """The convention PR14a fixed, checked across two independently written verticals: a
    reading is established, a conclusion drawn from one is a hypothesis and less confident."""
    for report in (_immortalization(**IMMO_RICH), _adipogenesis(**ADIPO_RICH).report):
        claims = [*report.supporting_evidence, *report.contradicting_evidence]
        assert claims
        for claim in claims:
            assert claim.tier in (EvidenceTier.ESTABLISHED, EvidenceTier.HYPOTHESIS)
            expected = (
                MEASUREMENT_CONFIDENCE
                if claim.tier is EvidenceTier.ESTABLISHED
                else INTERPRETATION_CONFIDENCE
            )
            assert claim.confidence == expected


def test_both_name_what_was_not_measured() -> None:
    """The one procedure the comparison found genuinely shared: required minus measured."""
    immo = _immortalization(PDL_trend="increasing", gammaH2AX="high")
    adipo = _adipogenesis(PPARG="high").report
    assert immo.missing_axes
    assert adipo.missing_axes
    # Declared order, not set order: a report a human reads must not shuffle between runs.
    assert (
        immo.missing_axes == _immortalization(PDL_trend="increasing", gammaH2AX="high").missing_axes
    )
    assert adipo.missing_axes == _adipogenesis(PPARG="high").report.missing_axes


def test_both_separate_a_limit_from_a_risk_from_a_next_step() -> None:
    """Three different fields because they answer three different questions. Whether a given
    vertical fills all three is its own policy — that they stay distinct is shared."""
    for report in (_immortalization(**IMMO_RICH), _adipogenesis(**ADIPO_RICH).report):
        assert isinstance(report.limitations, list)
        assert isinstance(report.overinterpretation_risk, list)
        assert isinstance(report.recommended_validation, list)
        assert isinstance(report.next_experiment, list)


def test_both_recommend_a_next_step_when_something_is_unmeasured() -> None:
    immo = _immortalization(PDL_trend="increasing", gammaH2AX="high")
    adipo = _adipogenesis(PPARG="high").report
    assert immo.next_experiment
    assert adipo.next_experiment


def test_neither_repeats_a_suggestion() -> None:
    """Order-preserving de-duplication: a repeated suggestion reads as emphasis nobody
    intended. Immortalization hand-rolls this today; adipogenesis has not needed it yet."""
    for report in (
        _immortalization(PDL_trend="increasing", gammaH2AX="high", p16="unknown", p21="unknown"),
        _adipogenesis().report,
    ):
        assert len(report.next_experiment) == len(set(report.next_experiment))
        assert len(report.recommended_validation) == len(set(report.recommended_validation))


def test_both_are_deterministic() -> None:
    assert _immortalization(**IMMO_RICH).model_dump(mode="json") == _immortalization(
        **IMMO_RICH
    ).model_dump(mode="json")
    assert _adipogenesis(**ADIPO_RICH).model_dump(mode="json") == _adipogenesis(
        **ADIPO_RICH
    ).model_dump(mode="json")


# --- domain-specific behaviour: what must stay different ---------------------


def test_the_two_status_vocabularies_do_not_overlap() -> None:
    """If they did, a shared status field would be tempting and wrong."""
    immortalization = {status.value for status in CandidateStatus}
    adipogenesis = {status.value for status in DifferentiationStatus}
    assert immortalization & adipogenesis == {"insufficient_evidence"}  # only "we cannot tell"
    assert "differentiating" not in immortalization
    assert "possible_candidate" not in adipogenesis


def test_each_domain_requires_its_own_axes() -> None:
    """Which axes must be measured is biology, and the two disagree completely."""
    immo = set(_immortalization().missing_axes)
    adipo = set(_adipogenesis().report.missing_axes)
    assert immo and adipo
    assert immo.isdisjoint(adipo)


def test_contradiction_logic_is_domain_specific() -> None:
    """The same shaped input means opposite things in the two domains."""
    # A high marker is a contradiction in immortalization...
    assert _immortalization(gammaH2AX="high").contradicting_evidence
    # ...while a high marker panel is what *supports* adipogenesis.
    supporting = _adipogenesis(PPARG="high", CEBPA="high", lipid_accumulation="high")
    assert supporting.status is DifferentiationStatus.DIFFERENTIATING
    assert supporting.report.supporting_evidence


def test_next_assay_policy_is_domain_specific() -> None:
    immo = " ".join(_immortalization().next_experiment).lower()
    adipo = " ".join(_adipogenesis().report.next_experiment).lower()
    assert "telomere" in immo and "telomere" not in adipo
    assert "oil red o" in adipo and "oil red o" not in immo


def test_adipogenesis_is_not_forced_into_trajectory_semantics() -> None:
    """The trajectory quartet is the first vertical's passage-series machinery. A domain with
    no temporal model must be able to leave all of it alone."""
    report = _adipogenesis(**ADIPO_RICH).report
    assert report.trajectory is None
    assert report.derived_input == {}
    assert report.input_conflicts == []
    assert report.blocked_overrides == []


def test_immortalization_still_uses_its_trajectory_machinery() -> None:
    """The other half of the same boundary: leaving it optional must not disable it."""
    report = _immortalization(
        PDL_trend="increasing",
        DT_trend="stable",
        gammaH2AX="low",
        observations=[
            {"passage": 10, "cumulative_PDL": 12.0, "DT_hours": 24.0},
            {"passage": 20, "cumulative_PDL": 20.0, "DT_hours": 30.0},
            {"passage": 30, "cumulative_PDL": 20.2, "DT_hours": 90.0},
        ],
    )
    assert report.trajectory is not None
    assert report.derived_input
    assert report.input_conflicts


# --- contract leakage: the consequence a second domain lives with ------------


def test_a_second_domain_cannot_state_its_verdict_in_the_first_one_s_vocabulary() -> None:
    """The residue the comparison identified.

    Asserted as the *consequence* rather than the mechanism: adipogenesis has a real verdict
    and it is not expressible as a `CandidateStatus`. PR14b may change where the verdict
    lives; it must not make this claim false by teaching one domain to speak the other's
    vocabulary.
    """
    outcome = _adipogenesis(PPARG="high", CEBPA="high", lipid_accumulation="high")
    assert outcome.status is DifferentiationStatus.DIFFERENTIATING
    assert outcome.status.value not in {status.value for status in CandidateStatus}


def test_the_second_domain_s_verdict_still_reaches_a_caller() -> None:
    """Wherever it lives, a caller must be able to read it. This is the invariant PR14b has
    to preserve, and the reason the residue is a design problem rather than a blocker."""
    from virtualcell.platform.contracts import ReasoningQuery
    from virtualcell.platform.packs.adipogenesis import AdipogenesisDomainPack

    response = AdipogenesisDomainPack().execute(
        ReasoningQuery.model_validate(
            {
                "domain": "adipogenesis",
                "task": "assess_state",
                "experiment": {"PPARG": "high", "CEBPA": "high", "lipid_accumulation": "high"},
            }
        ),
        _store(),
    )
    assert response.decision_support.status == "differentiating"


@pytest.mark.parametrize("field", ["cell_type_relevance", "species_relevance", "actionability"])
def test_the_relevance_scores_are_unimplemented_in_both_verticals(field: str) -> None:
    """Not first-vertical residue — speculative fields with no implementation anywhere after
    two verticals. Recorded so whoever adds a third domain decides to specify or delete them,
    rather than inheriting them a third time."""
    assert getattr(_immortalization(**IMMO_RICH), field) is None
    assert getattr(_adipogenesis(**ADIPO_RICH).report, field) is None
