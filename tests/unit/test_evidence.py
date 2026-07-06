"""Tests for the evidence tier system."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.core.evidence import Claim, EvidenceTier


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
