"""Tests for the Q9 hypothesis policy (PR5c-2)."""

from __future__ import annotations

import pytest

from virtualcell.agents.immortalization.grounding import GroundingError
from virtualcell.agents.immortalization.hypotheses import (
    HypothesisSafetyError,
    UnsupportedHypothesisError,
    build_hypothesis_report,
    validate_hypothesis_report,
)
from virtualcell.agents.immortalization.models import ImmortalizationAssessmentInput
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import CandidateStatus, DecisionReport

_ALLOWED = {
    "mechanism:telomere_maintenance",
    "mechanism:mitochondrial_function",
    "mechanism:spontaneous_immortalization",
    "phenotype:sustained_proliferation",
}
_FORBIDDEN_TARGETS = {"mechanism:g1s_progression", "mechanism:p16_rb_arrest", "gene:CDK4"}


def _seeded() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


def _report() -> DecisionReport:
    data = ImmortalizationAssessmentInput(intent="hypothesis_handling")
    return build_hypothesis_report(data, _seeded())


def test_wrong_intent_raises() -> None:
    with pytest.raises(UnsupportedHypothesisError):
        build_hypothesis_report(
            ImmortalizationAssessmentInput(intent="immortalization_assessment"), _seeded()
        )


def test_status_is_insufficient_and_flags_empty() -> None:
    report = _report()
    assert report.candidate_status == CandidateStatus.INSUFFICIENT_EVIDENCE
    assert report.flags == []


def test_required_claims_and_p53_wording() -> None:
    report = _report()
    assert len(report.supporting_evidence) == 4

    p53_claim = next(c for c in report.supporting_evidence if "P53-independent" in c.statement)
    assert p53_claim.tier == EvidenceTier.HYPOTHESIS
    assert p53_claim.citations  # citation required, not empty
    assert "without activating P53" in p53_claim.statement

    blob = " ".join(c.statement for c in report.supporting_evidence).lower()
    for forbidden in ("without p53", "p53 loss", "p53 knockout", "p53 deletion"):
        assert forbidden not in blob


def test_causation_is_not_asserted() -> None:
    report = _report()
    blob = " ".join(c.statement for c in report.supporting_evidence).lower()
    assert "does not establish causation" in blob
    assert "causes spontaneous immortalization" not in blob


def test_strong_context_and_weak_spontaneous_links() -> None:
    report = _report()
    chain = report.mechanistic_chain
    targets = {link.target_id for link in chain}

    # Established supporting context.
    assert "mechanism:telomere_maintenance" in targets
    assert "mechanism:mitochondrial_function" in targets
    # Weak spontaneous route present, reaching sustained proliferation via it.
    assert "mechanism:spontaneous_immortalization" in targets
    sustained = [link for link in chain if link.target_id == "phenotype:sustained_proliferation"]
    assert sustained
    for link in sustained:
        steps = " ".join(link.path)
        assert "associated_with" in steps and "suggests" in steps


def test_weak_route_never_reads_as_established() -> None:
    for link in _report().mechanistic_chain:
        if any("associated_with" in s or "suggests" in s for s in link.path):
            assert link.tier != EvidenceTier.ESTABLISHED


def test_no_leakage_outside_allowlist_or_via_cdk4() -> None:
    chain = _report().mechanistic_chain
    for link in chain:
        assert link.target_id in _ALLOWED
        assert link.target_id not in _FORBIDDEN_TARGETS
        assert "CDK4" not in " ".join(link.path)


def test_no_duplicate_paths() -> None:
    keys = [(link.target_id, tuple(link.path)) for link in _report().mechanistic_chain]
    assert len(keys) == len(set(keys))


def test_missing_seed_raises_grounding_error() -> None:
    with pytest.raises(GroundingError):
        build_hypothesis_report(
            ImmortalizationAssessmentInput(intent="hypothesis_handling"), InMemoryKnowledgeStore()
        )


def test_safety_validator_rejects_forbidden_phrasing() -> None:
    bad = DecisionReport(
        conclusion="The spontaneous route works via P53 loss.",  # forbidden
        candidate_status=CandidateStatus.INSUFFICIENT_EVIDENCE,
        supporting_evidence=[Claim(statement="x", tier=EvidenceTier.HYPOTHESIS)],
    )
    with pytest.raises(HypothesisSafetyError):
        validate_hypothesis_report(bad)
