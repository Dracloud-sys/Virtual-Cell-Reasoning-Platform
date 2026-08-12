"""Adipogenesis assessment input and its status vocabulary (minimal second vertical).

Marker values are normalized labels, deliberately coarse: ``high | low | absent | unknown``
(or omitted). A minimal vertical has no business inventing a quantitative scale it cannot
validate, and a coarse label that is honest beats a number that is not.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AdipogenesisIntent(StrEnum):
    """What the caller is asking about."""

    DIFFERENTIATION_ASSESSMENT = "differentiation_assessment"
    MECHANISM_EXPLANATION = "mechanism_explanation"


class DifferentiationStatus(StrEnum):
    """This domain's own coarse verdict.

    Four values, not three, because *why* a culture is not differentiating changes what a
    researcher does next: a program that never started is a protocol question, while a
    program held down by WNT or DLK1 is a biology question. Collapsing them would throw
    away the more actionable finding.
    """

    DIFFERENTIATING = "differentiating"
    NOT_DIFFERENTIATING = "not_differentiating"
    DIFFERENTIATION_INHIBITED = "differentiation_inhibited"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AdipogenesisFlag(StrEnum):
    """Orthogonal flags reported alongside — never instead of — the status."""

    FUNCTION_UNMEASURED = "function_unmeasured"
    """The transcriptional panel was read but nothing measured lipid. The most common way
    to overcall differentiation, so it is a flag rather than a footnote."""

    INHIBITOR_ACTIVE = "inhibitor_active"
    MARKERS_INCOMPLETE = "markers_incomplete"


# The molecular panel, and the functional axis it can never substitute for.
MOLECULAR_MARKERS: tuple[str, ...] = ("PPARG", "CEBPA", "FABP4", "ADIPOQ")
FUNCTIONAL_MARKER = "lipid_accumulation"
INHIBITOR_MARKERS: tuple[str, ...] = ("WNT_signalling", "DLK1")

_PRESENT = ("high",)
_ABSENT = ("low", "absent")


class AdipogenesisAssessmentInput(BaseModel):
    """One adipogenesis question. Absent markers stay absent; nothing is defaulted."""

    model_config = ConfigDict(extra="forbid")

    intent: AdipogenesisIntent = AdipogenesisIntent.DIFFERENTIATION_ASSESSMENT
    species: str | None = None
    cell_type: str | None = None

    PPARG: str | None = None  # noqa: N815 - marker names mirror the gene symbols
    CEBPA: str | None = None  # noqa: N815
    FABP4: str | None = None  # noqa: N815
    ADIPOQ: str | None = None  # noqa: N815
    lipid_accumulation: str | None = None
    WNT_signalling: str | None = None  # noqa: N815
    DLK1: str | None = None  # noqa: N815

    induction_days: int | None = Field(default=None, ge=0)
    measurements: dict[str, str] = Field(default_factory=dict)
    """Anything else the caller recorded, carried through untouched and never interpreted."""

    def value(self, marker: str) -> str | None:
        return getattr(self, marker, None)

    def measured(self, markers: tuple[str, ...]) -> list[str]:
        """Markers with any reading at all — ``unknown`` is not a reading."""
        return [m for m in markers if self.value(m) not in (None, "unknown")]

    def positive(self, markers: tuple[str, ...]) -> list[str]:
        return [m for m in markers if self.value(m) in _PRESENT]

    def negative(self, markers: tuple[str, ...]) -> list[str]:
        return [m for m in markers if self.value(m) in _ABSENT]
