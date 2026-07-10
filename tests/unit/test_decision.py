"""Tests for the DecisionReport contract (PR4b)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.core.contracts import AgentOutput
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import AssessmentFlag, CandidateStatus, DecisionReport
from virtualcell.reasoning.explain import explain


def _seeded() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


def test_scaffold_wires_mechanistic_chain_from_explain() -> None:
    expl = explain(_seeded(), "gene:CDK4", max_hops=2)
    report = DecisionReport.scaffold(
        "CDK4 drives G1/S and functionally bypasses the p16-RB checkpoint.",
        expl,
        overinterpretation_risk=["Immortalization is not safety or retained function."],
        next_experiment=["Karyotype", "Differentiation assay"],
    )
    # The mechanistic chain is exactly explain's links (the two primitives compose).
    assert report.mechanistic_chain == expl.links
    assert report.mechanistic_chain
    assert report.candidate_status is None  # a mechanism report has no status
    assert report.next_experiment


def test_report_represents_benchmark_required_output() -> None:
    # A Q2-style assessment: possible_candidate with both sides + risk + next steps.
    report = DecisionReport(
        conclusion="Possible immortalization candidate; verification incomplete.",
        candidate_status="possible_candidate",
        supporting_evidence=[
            Claim(
                statement="PDL increasing, DT stable, gammaH2AX low -> proliferation continues.",
                tier=EvidenceTier.ESTABLISHED,
                confidence=0.8,
                citations=["kb:marker:PDL"],
            )
        ],
        contradicting_evidence=[
            Claim(
                statement="p16/p21/SA-b-Gal unmeasured; TERT/telomere unverified.",
                tier=EvidenceTier.HYPOTHESIS,
            )
        ],
        overinterpretation_risk=["Do not call immortalization from PDL-up + gammaH2AX-low alone."],
        next_experiment=["Long-term PDL tracking", "SA-b-Gal", "p16/p21 qPCR", "telomere/TERT"],
    )

    # Every benchmark required_output field is representable.
    assert report.candidate_status == "possible_candidate"
    assert report.supporting_evidence and report.contradicting_evidence
    assert report.overinterpretation_risk and report.next_experiment
    # Q9 discipline: evidence carries tier + citations for claim decomposition.
    assert report.supporting_evidence[0].tier == EvidenceTier.ESTABLISHED
    assert report.supporting_evidence[0].citations == ["kb:marker:PDL"]
    # Serializes cleanly (for the API / agent output).
    assert report.model_dump()["candidate_status"] == "possible_candidate"


def test_functionality_flag_is_representable() -> None:
    # Q7: proliferation looks fine but differentiation is lost.
    report = DecisionReport(
        conclusion="Proliferation sustained but differentiation compromised.",
        candidate_status="possible_candidate",
        flags=["functionality_compromised"],
    )
    assert AssessmentFlag.FUNCTIONALITY_COMPROMISED in report.flags


def test_status_and_flags_are_enum_validated() -> None:
    # A typo in the status must not slip through (GPT review item).
    with pytest.raises(ValidationError):
        DecisionReport(conclusion="x", candidate_status="possible_candidtae")
    with pytest.raises(ValidationError):
        DecisionReport(conclusion="x", flags=["not_a_flag"])
    # Valid enum values (as strings) are accepted and coerced.
    report = DecisionReport(conclusion="x", candidate_status="insufficient_evidence")
    assert report.candidate_status is CandidateStatus.INSUFFICIENT_EVIDENCE


def test_relevance_scores_are_bounded_and_default_none() -> None:
    assert DecisionReport(conclusion="x").cell_type_relevance is None
    with pytest.raises(ValidationError):
        DecisionReport(conclusion="x", cell_type_relevance=1.5)


def test_new_benchmark_fields_present() -> None:
    report = DecisionReport(
        conclusion="Conflicting acute-damage vs chronic-senescence signals.",
        missing_axes=["p16", "telomere_length"],
        conflict_explanation=["gammaH2AX/p21 up (acute) vs SA-b-Gal low, p16 normal (chronic)"],
        limitations=["TERT alone does not bypass the p16/RB checkpoint."],
    )
    assert report.missing_axes == ["p16", "telomere_length"]
    assert report.conflict_explanation and report.limitations


def test_agent_output_preserves_structured_result() -> None:
    report = DecisionReport(conclusion="ok", candidate_status="possible_candidate")
    out = AgentOutput(agent="immortalization", result=report.model_dump())
    # The full DecisionReport survives on the common agent contract, not just notes.
    assert out.result["candidate_status"] == "possible_candidate"
