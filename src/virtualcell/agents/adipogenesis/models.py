"""Adipogenesis assessment input, axes and status vocabulary (full second vertical).

Six axes, each earning its place by changing a decision — see `docs/adipogenesis_vertical.md`
for the reasoning behind every inclusion and the three candidates that were excluded.

Marker values are coarse labels: ``high | low | absent | unknown`` (or omitted). A vertical
with no validated quantitative scale has no business inventing one, and an honest coarse
label beats a number nobody can defend. ``unknown`` and omitted mean the same thing: no
reading was taken.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AdipogenesisIntent(StrEnum):
    """What the caller is asking about."""

    DIFFERENTIATION_ASSESSMENT = "differentiation_assessment"
    MECHANISM_EXPLANATION = "mechanism_explanation"


class DifferentiationStatus(StrEnum):
    """This domain's verdict on the differentiation question.

    Five values, and the two that are *absent* matter as much as the ones present.

    There is no ``mature``: proving maturity from a marker panel is precisely the overclaim
    this vertical forbids, so maturity is an axis and a validation recommendation, never a
    verdict. There is no "culture compromised" either — low viability yields
    ``insufficient_evidence`` plus a flag, because the honest statement is "we cannot judge
    this", not "this is a different biological state".
    """

    DIFFERENTIATING = "differentiating"
    PARTIALLY_DIFFERENTIATED = "partially_differentiated"
    NOT_DIFFERENTIATING = "not_differentiating"
    DIFFERENTIATION_INHIBITED = "differentiation_inhibited"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AdipogenesisFlag(StrEnum):
    """Orthogonal signals reported alongside — never instead of — the status."""

    FUNCTION_UNMEASURED = "function_unmeasured"
    """The transcriptional panel was read but nothing measured lipid. The most common way to
    overcall differentiation, so it is a flag rather than a footnote."""

    INHIBITOR_ACTIVE = "inhibitor_active"
    MARKERS_INCOMPLETE = "markers_incomplete"

    LATE_PROGRAM_ABSENT = "late_program_absent"
    """Commitment markers are up but the completion markers are not. Expected early in an
    induction, a failure late in one — which is why the induction day is read."""

    VIABILITY_COMPROMISED = "viability_compromised"
    """A culture in poor condition cannot support a *negative* call: "not differentiating"
    and "dying" look identical from a marker panel and have different fixes."""

    CONFLICTING_EVIDENCE = "conflicting_evidence"
    """Lipid without the program that should produce it. Often media loading rather than
    differentiation, and the distinction changes what the result means."""

    MATURATION_UNVERIFIED = "maturation_unverified"
    """Differentiation is under way and maturity was not established. Always true unless
    maturity markers were measured, and stated so it is never assumed."""


# --- axes ---------------------------------------------------------------------
#
# The program has a temporal order, and that order carries decision value: early-only is a
# different state from complete, with a different action.

EARLY_PROGRAM: tuple[str, ...] = ("PPARG", "CEBPA")
"""Commitment. Without the master regulators nothing downstream means differentiation."""

LATE_PROGRAM: tuple[str, ...] = ("FABP4", "ADIPOQ", "PLIN1")
"""Completion. Distinguishes a program that started from one that finished."""

MOLECULAR_MARKERS: tuple[str, ...] = (*EARLY_PROGRAM, *LATE_PROGRAM)

FUNCTIONAL_MARKER = "lipid_accumulation"
EFFICIENCY_MARKER = "lipid_efficiency"
"""How much of the culture accumulated lipid. 5% and 80% are different results."""

INHIBITOR_MARKERS: tuple[str, ...] = ("WNT_signalling", "DLK1")
VIABILITY_MARKER = "viability"
MORPHOLOGY_MARKER = "morphology"
"""Corroborating only: rounded, droplet-bearing cells support a call and never make one."""

MATURATION_MARKERS: tuple[str, ...] = ("ADIPOQ", "PLIN1")
"""Read for the *maturity* question only. Sharing markers with the late program is real
biology, not duplication — the same reading answers two different questions."""

REQUIRED_AXES: tuple[str, ...] = (*MOLECULAR_MARKERS, FUNCTIONAL_MARKER)
"""What must be measured before a differentiation call is possible. Efficiency, inhibition,
viability and morphology are optional: they refine or block a call, never enable one."""

# The induction day past which absent completion markers stop being "early days" and start
# being a failed differentiation. Deliberately generous — calling failure too early is the
# more expensive mistake, because the culture is discarded.
LATE_PROGRAM_EXPECTED_BY_DAY = 6

_PRESENT = ("high",)
_ABSENT = ("low", "absent")
_NO_READING = (None, "unknown")


class AdipogenesisAssessmentInput(BaseModel):
    """One adipogenesis question. Absent markers stay absent; nothing is defaulted."""

    model_config = ConfigDict(extra="forbid")

    intent: AdipogenesisIntent = AdipogenesisIntent.DIFFERENTIATION_ASSESSMENT
    species: str | None = None
    cell_type: str | None = None

    # A. early program / B. late program
    PPARG: str | None = None  # noqa: N815 - marker names mirror the gene symbols
    CEBPA: str | None = None  # noqa: N815
    FABP4: str | None = None  # noqa: N815
    ADIPOQ: str | None = None  # noqa: N815
    PLIN1: str | None = None  # noqa: N815
    # C. functional lipid
    lipid_accumulation: str | None = None
    lipid_efficiency: str | None = None
    # D. inhibition
    WNT_signalling: str | None = None  # noqa: N815
    DLK1: str | None = None  # noqa: N815
    # E. viability / F. morphology
    viability: str | None = None
    morphology: str | None = None

    induction_day: int | None = Field(default=None, ge=0)
    """Days since induction. Not a time series — a modifier. The same readings mean
    different things on day 2 and day 14, and that is worth knowing without any temporal
    machinery."""

    measurements: dict[str, str] = Field(default_factory=dict)
    """Anything else the caller recorded, carried through untouched and never interpreted."""

    def value(self, marker: str) -> str | None:
        return getattr(self, marker, None)

    def measured(self, markers: tuple[str, ...]) -> list[str]:
        """Markers with any reading at all — ``unknown`` is not a reading."""
        return [m for m in markers if self.value(m) not in _NO_READING]

    def positive(self, markers: tuple[str, ...]) -> list[str]:
        return [m for m in markers if self.value(m) in _PRESENT]

    def negative(self, markers: tuple[str, ...]) -> list[str]:
        return [m for m in markers if self.value(m) in _ABSENT]

    def is_present(self, marker: str) -> bool:
        return self.value(marker) in _PRESENT

    def is_absent(self, marker: str) -> bool:
        return self.value(marker) in _ABSENT

    def has_reading(self, marker: str) -> bool:
        return self.value(marker) not in _NO_READING

    @property
    def within_early_induction(self) -> bool:
        """Is it still early enough that missing completion markers are expected?

        Only a *stated* early day withholds a failure call. An unstated day does not
        manufacture doubt — the caller who omits it has said nothing, and treating silence as
        "too early" would quietly make the day a required field.
        """
        return self.induction_day is not None and self.induction_day < LATE_PROGRAM_EXPECTED_BY_DAY
