"""Tests for the mechanism/hypothesis DecisionReport builder (PR9-b)."""

from __future__ import annotations

import pytest

from virtualcell.agents.immortalization.mechanism import (
    UnsupportedMechanismIntentError,
    build_mechanism_report,
)
from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ConstructType,
    ImmortalizationAssessmentInput,
)
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import CandidateStatus

_FORBIDDEN = ["without p53", "p53 loss", "p53 knockout", "causes spontaneous immortalization"]


@pytest.fixture
def store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    source = ImmortalizationSeedSource()
    for entity in source.entities():
        store.upsert(entity)
    for interaction in source.interactions():
        store.add_interaction(interaction)
    return store


def _mech(store, construct):
    return build_mechanism_report(
        store,
        ImmortalizationAssessmentInput(
            intent=AssessmentIntent.MECHANISM_EXPLANATION, construct_type=construct
        ),
    )


def _text(report) -> str:
    parts = [
        report.conclusion,
        *report.limitations,
        *report.overinterpretation_risk,
        *report.next_experiment,
        *(link.target_name for link in report.mechanistic_chain),
        *(c.statement for c in report.supporting_evidence),
    ]
    return " ".join(parts).lower()


# --- mechanism (Q5 / Q6) -----------------------------------------------------


def test_tert_only_mechanism_report(store) -> None:
    report = _mech(store, ConstructType.TERT_ONLY)
    assert report.candidate_status is None  # a mechanism question carries no status
    assert report.mechanistic_chain  # derived from the seed graph
    text = _text(report)
    assert "telomere" in text  # TERT -> telomere maintenance
    # Its key limitation: TERT does not bypass p16/RB and CDK4 may be needed.
    assert any("does not bypass" in lim.lower() for lim in report.limitations)
    assert "cdk4" in text and "p16" in text
    assert any("p16" in step.lower() for step in report.next_experiment)


def test_tert_only_chain_is_tier_graded(store) -> None:
    report = _mech(store, ConstructType.TERT_ONLY)
    # The direct TERT -> telomere-maintenance edge is established; a downstream link is not.
    telomere = next(
        (
            link
            for link in report.mechanistic_chain
            if "telomere maintenance" in link.target_name.lower()
        ),
        None,
    )
    assert telomere is not None and telomere.tier is EvidenceTier.ESTABLISHED


def test_tert_plus_cdk4_mechanism_report(store) -> None:
    report = _mech(store, ConstructType.TERT_PLUS_CDK4)
    assert report.candidate_status is None
    text = _text(report)
    assert "bypass" in text  # CDK4 bypasses the p16/RB checkpoint
    # The essential caveat: immortalization is not safety or function.
    assert any("not safety or function" in lim.lower() for lim in report.limitations)
    nxt = " ".join(report.next_experiment).lower()
    assert ("karyotype" in nxt or "stability" in nxt) and "differentiation" in nxt


# --- hypothesis (Q9) ---------------------------------------------------------


def test_hypothesis_report_status_and_claims(store) -> None:
    report = build_mechanism_report(
        store,
        ImmortalizationAssessmentInput(intent=AssessmentIntent.HYPOTHESIS_HANDLING),
    )
    assert report.candidate_status is CandidateStatus.INSUFFICIENT_EVIDENCE
    tiers = [c.tier for c in report.supporting_evidence]
    # Two established associations (TERT/telomere, PGC1A/mito) + two hypotheses.
    assert tiers.count(EvidenceTier.ESTABLISHED) == 2
    assert tiers.count(EvidenceTier.HYPOTHESIS) == 2
    # The spontaneous-route claim must be flagged as needing a citation.
    spontaneous = next(
        c for c in report.supporting_evidence if "p53-independent" in c.statement.lower()
    )
    assert spontaneous.tier is EvidenceTier.HYPOTHESIS
    assert spontaneous.citations


def test_hypothesis_report_avoids_forbidden_p53_phrasings(store) -> None:
    report = build_mechanism_report(
        store,
        ImmortalizationAssessmentInput(intent=AssessmentIntent.HYPOTHESIS_HANDLING),
    )
    text = _text(report)
    for phrase in _FORBIDDEN:
        assert phrase not in text, f"forbidden phrasing present: {phrase!r}"
    # It must still state the correct framing.
    assert "p53-independent" in text


def test_hypothesis_reach_stays_weak(store) -> None:
    report = build_mechanism_report(
        store,
        ImmortalizationAssessmentInput(intent=AssessmentIntent.HYPOTHESIS_HANDLING),
    )
    spontaneous = next(
        (link for link in report.mechanistic_chain if "spontaneous" in link.target_name.lower()),
        None,
    )
    # Reached only through ASSOCIATED_WITH / SUGGESTS, so never established.
    assert spontaneous is not None
    assert spontaneous.tier is not EvidenceTier.ESTABLISHED


# --- guardrails --------------------------------------------------------------


def test_assessment_intent_is_refused(store) -> None:
    with pytest.raises(UnsupportedMechanismIntentError):
        build_mechanism_report(
            store,
            ImmortalizationAssessmentInput(intent=AssessmentIntent.IMMORTALIZATION_ASSESSMENT),
        )


def test_reports_are_deterministic(store) -> None:
    a = _mech(store, ConstructType.TERT_PLUS_CDK4)
    b = _mech(store, ConstructType.TERT_PLUS_CDK4)
    assert a.model_dump() == b.model_dump()
