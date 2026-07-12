"""Tests for Q5/Q6 mechanism graph grounding (PR5c-1)."""

from __future__ import annotations

import pytest

from virtualcell.agents.immortalization.grounding import GroundingError, build_mechanism_report
from virtualcell.agents.immortalization.models import ImmortalizationAssessmentInput
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

_Q6_ALLOWED = {
    "mechanism:telomere_maintenance",
    "mechanism:replicative_senescence",
    "mechanism:p16_rb_arrest",
    "mechanism:g1s_progression",
    "phenotype:sustained_proliferation",
}


def _seeded() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


def _report(construct: str):
    data = ImmortalizationAssessmentInput(intent="mechanism_explanation", construct_type=construct)
    return build_mechanism_report(data, _seeded())


def test_q5_has_no_status_and_keeps_the_limitation() -> None:
    report = _report("TERT_only")
    assert report.candidate_status is None
    assert report.flags == []
    assert any("does not bypass" in lim.lower() for lim in report.limitations)
    # The TERT -> telomere maintenance path is grounded from the graph.
    assert any(
        link.target_id == "mechanism:telomere_maintenance" and "TERT" in link.path[0]
        for link in report.mechanistic_chain
    )
    assert all(
        link.target_id in {"mechanism:telomere_maintenance", "mechanism:replicative_senescence"}
        for link in report.mechanistic_chain
    )


def test_q6_has_both_arms_within_the_allowlist() -> None:
    report = _report("TERT_plus_CDK4")
    targets = {link.target_id for link in report.mechanistic_chain}
    # TERT arm and CDK4 arm both present.
    assert "mechanism:telomere_maintenance" in targets  # TERT arm
    assert "mechanism:p16_rb_arrest" in targets  # CDK4 arm
    assert "phenotype:sustained_proliferation" in targets  # CDK4 -> G1/S -> proliferation
    # Nothing outside the intent allowlist leaks in (e.g. next-test assays).
    assert targets <= _Q6_ALLOWED
    # The P53-independent spontaneous route (Q9's domain, a weak-relation path) must
    # not leak into the Q6 mechanism chain even though it shares a target.
    for link in report.mechanistic_chain:
        assert not any("associated_with" in step or "suggests" in step for step in link.path)
        assert not any("spontaneous" in step.lower() for step in link.path)


def test_cdk4_is_not_stated_as_directly_inhibiting_p16() -> None:
    report = _report("TERT_plus_CDK4")
    text = " ".join([report.conclusion, *(c.statement for c in report.supporting_evidence)]).lower()
    assert "directly inhibits p16" not in text


def test_chain_has_no_duplicate_paths() -> None:
    report = _report("TERT_plus_CDK4")
    keys = [(link.target_id, tuple(link.path)) for link in report.mechanistic_chain]
    assert len(keys) == len(set(keys))


def test_catalog_claim_tiers_and_citations_are_unchanged() -> None:
    report = _report("TERT_plus_CDK4")
    assert report.supporting_evidence  # non-empty
    for claim in report.supporting_evidence:
        assert claim.tier == EvidenceTier.ESTABLISHED
        assert claim.citations == ["curated:immortalization_seed"]


def test_missing_seed_entity_raises_grounding_error() -> None:
    data = ImmortalizationAssessmentInput(
        intent="mechanism_explanation", construct_type="TERT_only"
    )
    with pytest.raises(GroundingError):
        build_mechanism_report(data, InMemoryKnowledgeStore())  # empty store, no seeds
