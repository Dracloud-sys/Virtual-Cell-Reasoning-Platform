"""Scientific evidence tiers and claims.

The platform never mixes established knowledge, hypotheses, and speculation.
Every biological statement produced by code is a :class:`Claim` carrying exactly
one :class:`EvidenceTier`. See ``docs/evidence-policy.md``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceTier(StrEnum):
    """The three mutually exclusive tiers of biological knowledge."""

    ESTABLISHED = "established"
    """Well-supported, textbook / curated-database biology."""

    HYPOTHESIS = "hypothesis"
    """Plausible and backed by some evidence, but not settled."""

    SPECULATIVE = "speculative"
    """Model-generated conjecture, unverified."""

    @property
    def rank(self) -> int:
        """Ordinal strength of the tier (higher = stronger)."""
        return {"speculative": 0, "hypothesis": 1, "established": 2}[self.value]


class Claim(BaseModel):
    """A single biological statement with an explicit evidence tier.

    ``confidence`` expresses uncertainty *within* a tier and must never be used to
    implicitly upgrade the tier itself.
    """

    statement: str
    tier: EvidenceTier
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    citations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    def is_at_least(self, tier: EvidenceTier) -> bool:
        """Return True if this claim's tier is at least as strong as ``tier``."""
        return self.tier.rank >= tier.rank
