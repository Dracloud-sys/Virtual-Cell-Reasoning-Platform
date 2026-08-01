"""Scientific evidence tiers, claims, and the provisional-evidence policy.

The platform never mixes established knowledge, hypotheses, and speculation.
Every biological statement produced by code is a :class:`Claim` carrying exactly
one :class:`EvidenceTier`. See ``docs/evidence-policy.md``.

:func:`is_unreviewed` is the **single** policy predicate deciding whether evidence is
provisional (and so may never be presented as ``ESTABLISHED``). It lives here, in
domain-neutral ``core``, so every layer shares one rule: no module re-implements the
classification, and ``reasoning`` needs no dependency on the literature pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

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


# --- provisional-evidence policy ---------------------------------------------
#
# Two *independent* signals mark evidence as provisional — awaiting human review rather
# than curated knowledge. Either alone is sufficient, because neither can be relied on to
# always accompany the other:
#
# 1. an explicit ``review_status = "pending_review"`` property on the node, and
# 2. an entity id / citation in a namespace reserved for unreviewed evidence (``lit:``,
#    written by literature ingestion).
#
# A fixture, migration, or hand-built graph can easily create a ``lit:`` node without the
# property; conversely a future non-``lit:`` source may carry the property alone. Checking
# both keeps the guarantee intact in either case, and over-capping is always the safe
# direction: this predicate can only ever weaken a tier, never strengthen one.
PENDING_REVIEW = "pending_review"
UNREVIEWED_ID_NAMESPACES: tuple[str, ...] = ("lit:",)
UNREVIEWED_TIER = EvidenceTier.HYPOTHESIS


def is_unreviewed_identifier(identifier: str | None) -> bool:
    """Does an entity id or citation name a reserved provisional-evidence namespace?

    Substring (not prefix) matching, because a citation composes ids — a mechanistic path
    reads ``kb:gene:TERT->kb:lit:marker:tert`` and must be caught by its endpoint.
    """
    return bool(identifier) and any(ns in identifier for ns in UNREVIEWED_ID_NAMESPACES)


def is_unreviewed(*anchors: Any) -> bool:
    """Is *any* anchor of a piece of evidence provisional rather than curated?

    An anchor is either an identifier/citation string or an entity-like object exposing
    ``id`` and ``properties`` (duck-typed, so ``core`` stays independent of the knowledge
    schema). Pass every node and citation a fact rests on — an entity, both endpoints of a
    path, the citation itself — and the fact is provisional if any one of them is.
    """
    for anchor in anchors:
        if anchor is None:
            continue
        if isinstance(anchor, str):
            if is_unreviewed_identifier(anchor):
                return True
            continue
        if is_unreviewed_identifier(getattr(anchor, "id", None)):
            return True
        properties = getattr(anchor, "properties", None)
        if isinstance(properties, Mapping) and properties.get("review_status") == PENDING_REVIEW:
            return True
    return False


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
