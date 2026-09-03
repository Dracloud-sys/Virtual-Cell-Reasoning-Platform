"""Genome-edit validation input, axes and status vocabulary — the third vertical.

The question: *does this clone carry the edit I intended, and can I use it?* Structurally
unlike the first two verticals, which both judge a cell state from marker readings. This one
judges a **molecular claim about a construct**, and it cannot do so from a value alone — it has
to know **how the value was measured** first.

    PCR band                   ->  a band is not a genotype
    Sanger / NGS + allele call ->  a genotype

That asymmetry is the domain's whole character. A negative from PCR is weak evidence of
absence; a negative from sequencing is a finding. Neither existing vertical has any notion that
evidence strength varies by instrument, which is why this domain was chosen — see
`docs/third_domain_selection.md`.

**Headline rule: a band is not a genotype.** The structural sibling of "a marker panel is not
a fat cell" and "sustained proliferation is not immortalization", reached from a different
direction.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EditingIntent(StrEnum):
    """What the caller is asking about."""

    EDIT_VALIDATION = "edit_validation"
    MECHANISM_EXPLANATION = "mechanism_explanation"


class EditStatus(StrEnum):
    """This domain's verdict on the edit-validation question.

    Four values, and the two that are *absent* are the safety boundary.

    There is no ``functional_knockout``: a confirmed DNA edit says nothing about whether the
    protein is gone, and inferring one from the other is the overclaim this vertical exists to
    refuse. There is no ``off_target_free`` either — three clean predicted sites are not a
    clean genome, and no assay this domain models can establish an absence across one.
    """

    EDITED_CLONAL = "edited_clonal"
    EDITED_MOSAIC = "edited_mosaic"
    UNEDITED = "unedited"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EditingFlag(StrEnum):
    """Orthogonal signals reported alongside — never instead of — the status."""

    WEAK_ASSAY = "weak_assay"
    """The edit was screened by a method that cannot read a genotype. The most common way an
    edit is overcalled, so it is a flag rather than a footnote."""

    CONTROL_MISSING = "control_missing"
    """No matched unedited parent. A difference needs something to differ from."""

    MOSAIC_POPULATION = "mosaic_population"
    """Editing happened; a clone did not. Expanding this as if it were clonal produces a line
    whose genotype drifts under selection."""

    CONFLICTING_EVIDENCE = "conflicting_evidence"
    """The screen and the independent confirmation disagree about the same locus."""

    OFF_TARGET_UNASSESSED = "off_target_unassessed"
    """Nobody looked, or looked only at predicted sites. Never cleared by this assessment,
    because the assessment cannot clear it."""

    FUNCTION_UNVERIFIED = "function_unverified"
    """The edit is at the DNA level and nobody measured the protein. Stated on every positive
    call so that "edited" is never read as "the gene is off"."""


class DetectionValue(StrEnum):
    """A locus readout. ``absent`` is a result; ``unknown`` is a gap."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class AssayValue(StrEnum):
    """How the edit was screened, ordered by what the method can actually resolve.

    ``pcr`` answers "did something amplify at the expected size". ``sanger`` and ``ngs`` read
    sequence, so they can answer what the allele is. The domain's rules turn on this
    distinction rather than on the value that came back.
    """

    PCR = "pcr"
    SANGER = "sanger"
    NGS = "ngs"
    UNKNOWN = "unknown"


SEQUENCE_LEVEL_ASSAYS: frozenset[AssayValue] = frozenset({AssayValue.SANGER, AssayValue.NGS})
"""The assays whose result is a genotype rather than a size. The one place assay strength is
written down, so a rule cannot quietly disagree with the description."""


class AllelePattern(StrEnum):
    """What the sequence says about the population, not about one allele."""

    HOMOZYGOUS = "homozygous"
    HETEROZYGOUS = "heterozygous"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ControlValue(StrEnum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    UNKNOWN = "unknown"


class OffTargetValue(StrEnum):
    """How far anyone looked for unintended edits.

    ``none`` and ``unknown`` differ in intent and not in consequence: neither supports a claim
    about the genome, and the flag is raised for both.
    """

    NONE = "none"
    PREDICTED_SITES = "predicted_sites"
    GENOME_WIDE = "genome_wide"
    UNKNOWN = "unknown"


class ExpressionValue(StrEnum):
    """Protein-level observation. ``absent`` is a real reading, not a gap."""

    CONFIRMED = "confirmed"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class EditType(StrEnum):
    KNOCKOUT = "knockout"
    KNOCK_IN = "knock_in"
    UNKNOWN = "unknown"


# --- axes ---------------------------------------------------------------------

REQUIRED_AXES: tuple[str, ...] = ("edit_detected", "edit_assay", "parental_control")
"""What a verdict is impossible without: a readout, the method that produced it, and something
to compare against.

``allele_pattern`` is deliberately *not* here even though it decides clonal-vs-mosaic. It is
only answerable once an edit was found, so requiring it would report a spurious gap on every
genuinely unedited clone — the same "we did not look" / "we looked and it was not there"
distinction the other two verticals protect, in a third guise.
"""


class EditingAssessmentInput(BaseModel):
    """One genome-edit validation question. Nothing is defaulted into existence."""

    model_config = ConfigDict(extra="forbid")

    intent: EditingIntent = EditingIntent.EDIT_VALIDATION
    species: str | None = None
    cell_type: str | None = None
    target_gene: str | None = None

    # A. what the screen found, and what it was capable of finding
    edit_detected: DetectionValue = DetectionValue.UNKNOWN
    edit_assay: AssayValue = AssayValue.UNKNOWN
    sequence_confirmed: DetectionValue = DetectionValue.UNKNOWN
    # B. what the population looks like
    allele_pattern: AllelePattern = AllelePattern.UNKNOWN
    # C. what it was compared against
    parental_control: ControlValue = ControlValue.UNKNOWN
    # D. refinement axes: they qualify a call and can never make one
    off_target_screened: OffTargetValue = OffTargetValue.UNKNOWN
    protein_expression: ExpressionValue = ExpressionValue.UNKNOWN

    edit_type: EditType = EditType.UNKNOWN
    """Which edit was attempted. Read by the mechanism task, and by the assessment only to
    choose what still needs confirming — a knock-in junction and a frameshift are different
    follow-ups."""

    measurements: dict[str, str] = Field(default_factory=dict)
    """Anything else the caller recorded, carried through untouched and never interpreted."""

    def value(self, axis: str) -> object:
        return getattr(self, axis, None)

    @property
    def sequence_level(self) -> bool:
        """Was the screen capable of reading a genotype at all?"""
        return self.edit_assay in SEQUENCE_LEVEL_ASSAYS

    @property
    def conflicting(self) -> bool:
        """A screen and an independent confirmation that cannot both be right."""
        return (
            self.edit_detected is DetectionValue.PRESENT
            and self.sequence_confirmed is DetectionValue.ABSENT
        ) or (
            self.edit_detected is DetectionValue.ABSENT
            and self.sequence_confirmed is DetectionValue.PRESENT
        )

    @property
    def off_target_assessed(self) -> bool:
        """Only a genome-wide search counts as having assessed the genome.

        ``predicted_sites`` is real work and is reported as such, but it answers a narrower
        question than the flag asks, so it does not clear it.
        """
        return self.off_target_screened is OffTargetValue.GENOME_WIDE
