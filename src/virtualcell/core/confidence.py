"""Confidence-estimation utilities.

Confidence is a value in [0, 1] expressing uncertainty *within* an evidence tier.
It is deliberately kept separate from :class:`~virtualcell.core.evidence.EvidenceTier`.
"""

from __future__ import annotations

from collections.abc import Iterable


def combine_confidences(values: Iterable[float]) -> float:
    """Combine independent confidences using a noisy-OR-style aggregation.

    Returns 0.0 for an empty input. The result is the complement of the product
    of complements: ``1 - prod(1 - v)``, which grows as corroborating evidence
    accumulates while never exceeding 1.0.
    """
    values = [max(0.0, min(1.0, v)) for v in values]
    if not values:
        return 0.0
    complement = 1.0
    for v in values:
        complement *= 1.0 - v
    return 1.0 - complement


def mean_confidence(values: Iterable[float]) -> float:
    """Simple arithmetic mean of confidences; 0.0 if empty."""
    values = [max(0.0, min(1.0, v)) for v in values]
    if not values:
        return 0.0
    return sum(values) / len(values)
