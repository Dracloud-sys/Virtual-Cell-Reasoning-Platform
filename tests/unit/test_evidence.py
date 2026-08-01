"""Tests for the evidence tier system."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.core.evidence import (
    UNREVIEWED_TIER,
    Claim,
    EvidenceTier,
    is_unreviewed,
    is_unreviewed_identifier,
)


def test_tier_ranking() -> None:
    assert EvidenceTier.ESTABLISHED.rank > EvidenceTier.HYPOTHESIS.rank
    assert EvidenceTier.HYPOTHESIS.rank > EvidenceTier.SPECULATIVE.rank


def test_claim_is_at_least() -> None:
    claim = Claim(statement="x", tier=EvidenceTier.HYPOTHESIS)
    assert claim.is_at_least(EvidenceTier.SPECULATIVE)
    assert claim.is_at_least(EvidenceTier.HYPOTHESIS)
    assert not claim.is_at_least(EvidenceTier.ESTABLISHED)


def test_confidence_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        Claim(statement="x", tier=EvidenceTier.SPECULATIVE, confidence=1.5)


# --- provisional-evidence policy (the single shared predicate) ---------------


class _Node:
    """Minimal entity-like stand-in (the predicate is duck-typed on purpose)."""

    def __init__(self, entity_id: str, properties: dict | None = None) -> None:
        self.id = entity_id
        self.properties = properties or {}


def test_unreviewed_by_namespace_alone() -> None:
    # A lit: node that never received a review_status — the exact gap a fixture,
    # migration or hand-built graph can create.
    assert is_unreviewed(_Node("lit:marker:tert"))
    assert is_unreviewed("kb:lit:assay:abc")


def test_unreviewed_by_review_status_alone() -> None:
    # A non-lit source explicitly awaiting review stays covered by the property rule.
    assert is_unreviewed(_Node("marker:experimental", {"review_status": "pending_review"}))


def test_curated_node_without_review_status_is_not_unreviewed() -> None:
    assert not is_unreviewed(_Node("gene:TERT"))
    assert not is_unreviewed("kb:gene:TERT")
    assert not is_unreviewed(_Node("gene:TERT", {"review_status": "reviewed"}))


def test_any_anchor_being_provisional_taints_the_fact() -> None:
    # A mechanistic path is only as strong as the weakest node it rests on: a curated
    # seed reaching a lit: endpoint (or via the composed citation) is provisional.
    assert is_unreviewed(_Node("gene:TERT"), _Node("lit:marker:tert"))
    assert is_unreviewed("kb:gene:TERT->kb:lit:marker:tert")
    assert not is_unreviewed(_Node("gene:TERT"), _Node("gene:CDK4"), "kb:gene:TERT")


def test_predicate_tolerates_missing_anchors() -> None:
    assert not is_unreviewed(None, "", _Node("gene:TERT"))


def test_identifier_helper_matches_substring_not_only_prefix() -> None:
    assert is_unreviewed_identifier("kb:lit:marker:tert")
    assert not is_unreviewed_identifier("kb:gene:TERT")
    assert not is_unreviewed_identifier(None)


def test_unreviewed_tier_is_below_established() -> None:
    assert UNREVIEWED_TIER.rank < EvidenceTier.ESTABLISHED.rank
