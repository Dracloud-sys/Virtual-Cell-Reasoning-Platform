"""Normalized input model for immortalization assessment (PR5a).

Strict, enum-validated input — the deterministic builder consumes this, not a
free-form marker dict. BYOD / CSV normalization is deferred; only the benchmark's
marker vocabulary is accepted here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AssessmentIntent(StrEnum):
    """The question intent. The PR5a builder handles the four *assessment* intents;
    mechanism/hypothesis intents are accepted here but explicitly rejected by the
    builder (they arrive in PR5b/PR5c)."""

    IMMORTALIZATION_ASSESSMENT = "immortalization_assessment"
    SENESCENCE_ASSESSMENT = "senescence_assessment"
    IMMORTALIZATION_VS_FUNCTIONALITY = "immortalization_vs_functionality"
    CONFLICTING_EVIDENCE_ASSESSMENT = "conflicting_evidence_assessment"
    MECHANISM_EXPLANATION = "mechanism_explanation"
    HYPOTHESIS_HANDLING = "hypothesis_handling"


# The four intents the deterministic builder can assess in PR5a.
ASSESSMENT_INTENTS = frozenset(
    {
        AssessmentIntent.IMMORTALIZATION_ASSESSMENT,
        AssessmentIntent.SENESCENCE_ASSESSMENT,
        AssessmentIntent.IMMORTALIZATION_VS_FUNCTIONALITY,
        AssessmentIntent.CONFLICTING_EVIDENCE_ASSESSMENT,
    }
)


class MarkerValue(StrEnum):
    """Normalized marker value vocabulary (benchmark labels only)."""

    HIGH = "high"
    LOW = "low"
    INCREASING = "increasing"
    PLATEAU = "plateau"
    STABLE = "stable"
    WORSENING = "worsening"
    IMPROVED = "improved"
    NORMAL = "normal"
    UNKNOWN = "unknown"


class ConstructType(StrEnum):
    """Engineered immortalization construct (drives the mechanism-rule catalog)."""

    TERT_ONLY = "TERT_only"
    TERT_PLUS_CDK4 = "TERT_plus_CDK4"
    UNKNOWN = "unknown"


class RetentionValue(StrEnum):
    """Differentiation-retention vocabulary.

    Split out from ``MarkerValue`` because retention reads ``retained``/``lost``,
    which the trend/level vocabulary cannot express (implementation constraint
    found while building against benchmark Q7 — flagged for GPT review).
    """

    RETAINED = "retained"
    LOST = "lost"
    UNKNOWN = "unknown"


class ImmortalizationAssessmentInput(BaseModel):
    """Enum-validated assessment input; a typo'd marker value is rejected."""

    intent: AssessmentIntent
    species: str | None = None
    cell_type: str | None = None
    # Named ``construct_type`` (not ``construct``) to avoid shadowing pydantic's
    # deprecated ``BaseModel.construct``; flagged for GPT review.
    construct_type: ConstructType = ConstructType.UNKNOWN

    # Field names deliberately mirror the benchmark marker vocabulary verbatim.
    PDL_trend: MarkerValue = MarkerValue.UNKNOWN
    DT_trend: MarkerValue = MarkerValue.UNKNOWN
    gammaH2AX: MarkerValue = MarkerValue.UNKNOWN  # noqa: N815
    SA_b_gal: MarkerValue = MarkerValue.UNKNOWN
    p16: MarkerValue = MarkerValue.UNKNOWN
    p21: MarkerValue = MarkerValue.UNKNOWN
    adipogenic_retention: RetentionValue = RetentionValue.UNKNOWN

    # Data not (yet) consumed by the baseline (e.g. DT_series, PPARG, OilRedO) is
    # preserved here rather than force-fit into the marker vocabulary.
    measurements: dict[str, Any] = Field(default_factory=dict)

    def marker_dict(self) -> dict[str, str]:
        """The marker mapping the deterministic ``baseline_status`` consumes."""
        return {
            "PDL_trend": self.PDL_trend,
            "DT_trend": self.DT_trend,
            "gammaH2AX": self.gammaH2AX,
            "SA_b_gal": self.SA_b_gal,
            "p16": self.p16,
            "p21": self.p21,
            "adipogenic_retention": self.adipogenic_retention,
        }
