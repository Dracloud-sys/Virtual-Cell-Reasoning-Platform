"""The evidence-tier conventions a decision report is built from (PR14a).

Two lines of code, and the most consequential thing in this package. A *measurement* is
something that was observed: it is ``ESTABLISHED``, and it carries the assumption that the
input was real and quality-controlled. An *interpretation* is what someone concludes from
that observation: it is a ``HYPOTHESIS``, and it is less confident.

Left to each vertical, those two decisions drift — one pack calls its interpretations
established, another rates measurements at 0.7 — and a drifting tier is a report that
overclaims without anything in the code looking wrong. The whole platform's epistemic
discipline rests on that distinction being made the same way everywhere, so it is made
here, once.
"""

from __future__ import annotations

from collections.abc import Sequence

from virtualcell.core.evidence import Claim, EvidenceTier

MEASUREMENT_CONFIDENCE = 0.9
"""High, but never 1.0: an instrument reading is still a reading."""

INTERPRETATION_CONFIDENCE = 0.7
"""Deliberately below a measurement's. Reading meaning into an observation adds a step
that can be wrong even when the observation is right."""

DEFAULT_MEASUREMENT_ASSUMPTIONS: tuple[str, ...] = (
    "Input measurements are valid and quality-controlled.",
)


def measurement_claim(
    statement: str,
    *,
    confidence: float = MEASUREMENT_CONFIDENCE,
    assumptions: Sequence[str] = DEFAULT_MEASUREMENT_ASSUMPTIONS,
    citations: Sequence[str] = (),
) -> Claim:
    """An observation, stated as established evidence with its assumption attached."""
    return Claim(
        statement=statement,
        tier=EvidenceTier.ESTABLISHED,
        confidence=confidence,
        assumptions=list(assumptions),
        citations=list(citations),
    )


def interpretation_claim(
    statement: str,
    *,
    confidence: float = INTERPRETATION_CONFIDENCE,
    citations: Sequence[str] = (),
) -> Claim:
    """A conclusion drawn from observations, stated as a hypothesis."""
    return Claim(
        statement=statement,
        tier=EvidenceTier.HYPOTHESIS,
        confidence=confidence,
        citations=list(citations),
    )
