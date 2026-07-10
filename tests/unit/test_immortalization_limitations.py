"""Tests for the Q5/Q6 mechanism-rule catalog (PR5b)."""

from __future__ import annotations

import pytest

from virtualcell.agents.immortalization.limitations import (
    MechanismRule,
    UnsupportedMechanismError,
    get_mechanism_rule,
)
from virtualcell.agents.immortalization.models import (
    ImmortalizationAssessmentInput,
)
from virtualcell.core.evidence import EvidenceTier

_FORBIDDEN = ["directly inhibits p16", "guarantees immortalization", "confirmed immortalized"]


def _mech(construct: str) -> MechanismRule:
    return get_mechanism_rule(
        ImmortalizationAssessmentInput(intent="mechanism_explanation", construct_type=construct)
    )


def test_tert_only_selects_q5_rule_with_limitation() -> None:
    rule = _mech("TERT_only")
    assert rule.rule_id == "TERT_only_p16_competent"
    assert "gene:TERT" in rule.seed_entity_ids
    # The crucial negative claim the graph cannot express.
    assert any("does not bypass" in c.statement.lower() for c in rule.limitations)
    # Mechanism rules carry no candidate status.
    assert "candidate_status" not in MechanismRule.model_fields


def test_tert_plus_cdk4_has_both_arms_and_safety_limits() -> None:
    rule = _mech("TERT_plus_CDK4")
    assert rule.rule_id == "TERT_plus_CDK4"
    supporting = " ".join(c.statement for c in rule.supporting_claims).lower()
    assert "tert" in supporting and "telomere" in supporting  # TERT arm
    assert "cdk4" in supporting and "bypass" in supporting  # CDK4 arm
    limits = " ".join(c.statement for c in rule.limitations).lower()
    assert "genomic stability" in limits
    assert "differentiation" in limits
    assert "non-tumorigenicity" in limits  # non-oncogenicity not asserted as established


def test_unknown_construct_and_wrong_intent_raise() -> None:
    with pytest.raises(UnsupportedMechanismError):
        _mech("unknown")
    with pytest.raises(UnsupportedMechanismError):
        get_mechanism_rule(
            ImmortalizationAssessmentInput(
                intent="immortalization_assessment", construct_type="TERT_only"
            )
        )


def test_claims_are_tiered_and_carry_no_fabricated_citations() -> None:
    for construct in ("TERT_only", "TERT_plus_CDK4"):
        rule = _mech(construct)
        for claim in [*rule.supporting_claims, *rule.limitations]:
            assert isinstance(claim.tier, EvidenceTier)
            # Only internal curated provenance — never a fabricated paper reference.
            for citation in claim.citations:
                assert citation.startswith("curated:")
                assert "http" not in citation and "doi" not in citation.lower()


def test_no_forbidden_phrasing_in_catalog() -> None:
    for construct in ("TERT_only", "TERT_plus_CDK4"):
        rule = _mech(construct)
        blob = " ".join(
            c.statement for c in [*rule.supporting_claims, *rule.limitations]
        ).lower()
        for phrase in _FORBIDDEN:
            assert phrase not in blob, f"forbidden phrasing: {phrase!r}"
