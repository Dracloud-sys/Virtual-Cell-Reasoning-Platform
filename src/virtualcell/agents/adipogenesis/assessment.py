"""Deterministic adipogenesis assessment — the second vertical's report builder.

Written against the PR14a/PR14b kernel and, deliberately, *not* by copying
``agents/immortalization/rules.py``. Everything biological lives here; everything procedural
comes from the kernel, which is not permitted to learn any of it.

The commitments this vertical is built around, in the order they matter:

1. **A marker panel is not a fat cell.** The PPARG/CEBPA program running says the cell is
   trying; lipid says it succeeded. A positive call requires both.
2. **A dying culture cannot be judged.** "Not differentiating" and "dying" look identical on
   a marker panel and have completely different fixes, so poor viability blocks a *negative*
   call rather than producing one.
3. **Lipid without the program is a conflict, not a success.** Cells load lipid from rich
   media without differentiating at all.
4. **Timing changes meaning.** Absent completion markers on day 2 is the expected course; on
   day 14 it is a failure.
5. **Differentiating is never mature.** Maturity is an axis and a recommendation, never a
   verdict.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.agents.adipogenesis.models import (
    EARLY_PROGRAM,
    EFFICIENCY_MARKER,
    FUNCTIONAL_MARKER,
    INHIBITOR_MARKERS,
    LATE_PROGRAM,
    LATE_PROGRAM_EXPECTED_BY_DAY,
    MATURATION_MARKERS,
    MOLECULAR_MARKERS,
    MORPHOLOGY_MARKER,
    REQUIRED_AXES,
    VIABILITY_MARKER,
    AdipogenesisAssessmentInput,
    AdipogenesisFlag,
    AdipogenesisIntent,
    DifferentiationStatus,
)
from virtualcell.core.evidence import Claim
from virtualcell.knowledge.schema import RelationType
from virtualcell.knowledge.sources.adipogenesis_seed import (
    ADIPOCYTE,
    CEBPA,
    COMMITMENT,
    LIPID_LADEN,
    LIPOGENESIS,
    MATURATION,
    PPARG,
    PROGRAM,
    UNDIFFERENTIATED,
    WNT10B,
    WNT_SIGNALLING,
)
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.decision import DecisionReport
from virtualcell.reasoning.kernel import (
    AssertionSafetyError,
    all_of,
    ground_links,
    interpretation_claim,
    measurement_claim,
    missing_axes,
    ordered_unique,
    relations_in,
    targets_in,
    validate_assertions,
)

_PROVENANCE = ["curated:adipogenesis_seed"]

# This pack's judgement about which relations may carry a mechanism claim — stated here
# rather than in the kernel because it is biology.
_MECHANISTIC_RELATIONS = (RelationType.PROMOTES, RelationType.INHIBITS)
_MECHANISM_SEEDS = [PPARG, CEBPA, WNT10B]
_MECHANISM_TARGETS = {
    COMMITMENT,
    PROGRAM,
    LIPOGENESIS,
    LIPID_LADEN,
    ADIPOCYTE,
    # The maturation *mechanism*, reached only through differentiation. The mature-adipocyte
    # phenotype is deliberately not a target: a chain terminating there would read as a
    # maturity claim, which is exactly what this vertical refuses to assert.
    MATURATION,
    WNT_SIGNALLING,
    UNDIFFERENTIATED,
}

# Phrasings this domain must never *assert*. Each is a real way to overclaim, and each is
# named in the report's own guidance — which is exactly why the kernel's assertion scope
# excludes the guidance fields from the check.
_FORBIDDEN = (
    "mature adipocyte",
    "fully differentiated",
    "terminally differentiated",
    "transdifferentiation",
    "proves the cells are fat",
    "ready for harvest",
    "suitable for consumption",
    "food safe",
)

_CONCLUSION = {
    DifferentiationStatus.DIFFERENTIATING: (
        "The adipogenic program is expressed and the culture has accumulated lipid, which "
        "together support ongoing adipogenic differentiation."
    ),
    DifferentiationStatus.PARTIALLY_DIFFERENTIATED: (
        "Commitment markers are expressed and lipid is detectable, but the completion "
        "markers were measured and are not up; the program appears to have started without "
        "finishing."
    ),
    DifferentiationStatus.NOT_DIFFERENTIATING: (
        "Neither the adipogenic transcription program nor lipid accumulation is detected "
        "after enough time to expect them; the culture does not appear to be differentiating "
        "under these conditions."
    ),
    DifferentiationStatus.DIFFERENTIATION_INHIBITED: (
        "An active inhibitory signal is present alongside an absent or incomplete adipogenic "
        "program, so the culture appears to be held in the preadipocyte state rather than "
        "simply failing to respond."
    ),
    DifferentiationStatus.INSUFFICIENT_EVIDENCE: (
        "The measured axes do not support a differentiation call; expression and lipid "
        "content answer different questions and both are needed."
    ),
}
_CONFLICT_CONCLUSION = (
    "Lipid is present without the transcriptional program that should produce it, so the "
    "readings do not agree; this is not yet a differentiation result."
)
_COMPROMISED_CONCLUSION = (
    "Culture viability is compromised, so an absence of differentiation markers cannot be "
    "distinguished from a culture that is failing for other reasons."
)

_LIMITATIONS = [
    "Marker expression reports that the adipogenic program is running, not that a mature "
    "adipocyte exists; maturity requires separate functional characterisation.",
    "This assessment says nothing about whether the resulting cells are safe, edible, or "
    "suitable for any downstream application.",
]
_RISKS = [
    "Do not read a positive qPCR panel as 'fully differentiated' - a program can run "
    "without the cell completing differentiation.",
    "Do not describe a lineage change here as transdifferentiation; nothing in this "
    "assessment distinguishes it from directed differentiation of a committed precursor.",
]


class AdipogenesisAssessment(BaseModel):
    """The report plus this domain's own verdict.

    The verdict travels beside the report rather than inside it, and that is a **finding**,
    not a preference: ``DecisionReport.candidate_status`` is typed to immortalization's
    vocabulary, and borrowing ``possible_candidate`` to mean "differentiating" would make two
    domains' statuses indistinguishable to every reader downstream. PR14b costed the
    migration and recorded that its trigger is a third domain, not general discomfort.
    """

    model_config = ConfigDict(extra="forbid")

    report: DecisionReport
    status: DifferentiationStatus
    flags: list[AdipogenesisFlag] = Field(default_factory=list)


class UnsupportedAdipogenesisIntentError(ValueError):
    """Raised when this builder is asked to answer something it does not handle."""


class AdipogenesisSafetyError(AssertionSafetyError):
    """Raised when an adipogenesis report asserts a forbidden overclaim."""


# --- the deterministic verdict -------------------------------------------------


def _is_conflicting(data: AdipogenesisAssessmentInput) -> bool:
    """Lipid without the program that should produce it.

    Cells load lipid from rich media without differentiating, so this is a disagreement
    between axes rather than a weak positive — and reporting it as a weak positive is how a
    medium artifact becomes a differentiation result.
    """
    return (
        data.is_present(FUNCTIONAL_MARKER)
        and bool(data.measured(EARLY_PROGRAM))
        and not data.positive(EARLY_PROGRAM)
    )


def _flags(data: AdipogenesisAssessmentInput) -> list[AdipogenesisFlag]:
    """What a reader must know alongside the status, whatever it turns out to be."""
    flags: list[AdipogenesisFlag] = []
    if data.positive(INHIBITOR_MARKERS):
        flags.append(AdipogenesisFlag.INHIBITOR_ACTIVE)
    if not data.has_reading(FUNCTIONAL_MARKER):
        flags.append(AdipogenesisFlag.FUNCTION_UNMEASURED)
    measured = data.measured(MOLECULAR_MARKERS)
    if 0 < len(measured) < len(MOLECULAR_MARKERS):
        flags.append(AdipogenesisFlag.MARKERS_INCOMPLETE)
    if (
        data.positive(EARLY_PROGRAM)
        and data.measured(LATE_PROGRAM)
        and not data.positive(LATE_PROGRAM)
    ):
        # Measured and negative. An *unmeasured* completion panel is a gap, reported by
        # MARKERS_INCOMPLETE and the missing axes - never as evidence of absence.
        flags.append(AdipogenesisFlag.LATE_PROGRAM_ABSENT)
    if data.is_absent(VIABILITY_MARKER):
        flags.append(AdipogenesisFlag.VIABILITY_COMPROMISED)
    if _is_conflicting(data):
        flags.append(AdipogenesisFlag.CONFLICTING_EVIDENCE)
    if not data.positive(MATURATION_MARKERS):
        flags.append(AdipogenesisFlag.MATURATION_UNVERIFIED)
    return flags


def _status(data: AdipogenesisAssessmentInput) -> DifferentiationStatus:
    """The deterministic verdict. No graph, no model — a stable regression anchor.

    Order matters, and the two *blocking* conditions come first because each describes a
    reason the readings cannot be trusted rather than a state of the biology.
    """
    early = bool(data.positive(EARLY_PROGRAM))
    late_positive = bool(data.positive(LATE_PROGRAM))
    late_measured = bool(data.measured(LATE_PROGRAM))
    lipid_present = data.is_present(FUNCTIONAL_MARKER)
    lipid_absent = data.is_absent(FUNCTIONAL_MARKER)
    inhibited = bool(data.positive(INHIBITOR_MARKERS))

    # Blocking: the axes disagree with each other.
    if _is_conflicting(data):
        return DifferentiationStatus.INSUFFICIENT_EVIDENCE

    # A positive call stands on its own evidence even in a struggling culture; it is the
    # *negative* call viability blocks, because dying and not-differentiating look alike.
    if early and lipid_present:
        # "Partial" means the completion markers were looked for and were not there. If
        # nobody looked, that is a gap in the evidence, not a stage of the biology - saying
        # otherwise would turn an unmeasured panel into a finding.
        if late_measured and not late_positive:
            return DifferentiationStatus.PARTIALLY_DIFFERENTIATED
        return DifferentiationStatus.DIFFERENTIATING

    if data.is_absent(VIABILITY_MARKER):
        return DifferentiationStatus.INSUFFICIENT_EVIDENCE

    if inhibited and not early:
        return DifferentiationStatus.DIFFERENTIATION_INHIBITED

    # A failure call needs the axes measured and no reason to think it is simply early.
    if (
        data.measured(MOLECULAR_MARKERS)
        and not early
        and lipid_absent
        and not data.within_early_induction
    ):
        return DifferentiationStatus.NOT_DIFFERENTIATING

    return DifferentiationStatus.INSUFFICIENT_EVIDENCE


# --- evidence ------------------------------------------------------------------

_ALL_MARKERS: tuple[str, ...] = (
    *MOLECULAR_MARKERS,
    FUNCTIONAL_MARKER,
    EFFICIENCY_MARKER,
    *INHIBITOR_MARKERS,
    VIABILITY_MARKER,
    MORPHOLOGY_MARKER,
)


def _observed(data: AdipogenesisAssessmentInput) -> list[Claim]:
    """What was measured, stated as measurements — never as conclusions."""
    claims = [
        measurement_claim(f"{marker} measured as {data.value(marker)}.", citations=_PROVENANCE)
        for marker in _ALL_MARKERS
        if data.has_reading(marker)
    ]
    if data.induction_day is not None:
        claims.append(
            measurement_claim(
                f"Assessed at induction day {data.induction_day}.", citations=_PROVENANCE
            )
        )
    return claims


def _supporting(data: AdipogenesisAssessmentInput, status: DifferentiationStatus) -> list[Claim]:
    claims = _observed(data)
    if status is DifferentiationStatus.DIFFERENTIATING:
        claims.append(
            interpretation_claim(
                "Expression of the adipogenic program together with measured lipid content "
                "is consistent with ongoing adipogenic differentiation.",
                citations=_PROVENANCE,
            )
        )
    if status is DifferentiationStatus.PARTIALLY_DIFFERENTIATED:
        claims.append(
            interpretation_claim(
                "Commitment markers with detectable lipid indicate the program has started; "
                "the completion markers would be expected to follow if induction continues.",
                citations=_PROVENANCE,
            )
        )
    if data.is_present(MORPHOLOGY_MARKER) and status in (
        DifferentiationStatus.DIFFERENTIATING,
        DifferentiationStatus.PARTIALLY_DIFFERENTIATED,
    ):
        claims.append(
            interpretation_claim(
                "Adipocyte-like morphology corroborates the molecular and functional "
                "readings; on its own it would not establish differentiation.",
                citations=_PROVENANCE,
            )
        )
    if data.is_present(EFFICIENCY_MARKER):
        claims.append(
            interpretation_claim(
                "A high proportion of the culture accumulated lipid, so the result reflects "
                "the population rather than a subpopulation.",
                citations=_PROVENANCE,
            )
        )
    return claims


def _contradicting(
    data: AdipogenesisAssessmentInput,
    status: DifferentiationStatus,
    flags: list[AdipogenesisFlag],
) -> list[Claim]:
    claims: list[Claim] = []
    if AdipogenesisFlag.INHIBITOR_ACTIVE in flags:
        active = ", ".join(data.positive(INHIBITOR_MARKERS))
        claims.append(
            interpretation_claim(
                f"An active inhibitory signal ({active}) argues against spontaneous "
                "adipogenic commitment under these conditions.",
                citations=_PROVENANCE,
            )
        )
    if AdipogenesisFlag.CONFLICTING_EVIDENCE in flags:
        claims.append(
            interpretation_claim(
                "Lipid is present without the commitment program; cells can load lipid from "
                "rich media without differentiating, so this does not support a "
                "differentiation call.",
                citations=_PROVENANCE,
            )
        )
    if AdipogenesisFlag.VIABILITY_COMPROMISED in flags:
        claims.append(
            interpretation_claim(
                "Reduced viability can suppress differentiation markers independently of "
                "adipogenic capacity, so an absent program cannot be attributed to the "
                "differentiation protocol.",
                citations=_PROVENANCE,
            )
        )
    if status is DifferentiationStatus.INSUFFICIENT_EVIDENCE and data.positive(MOLECULAR_MARKERS):
        claims.append(
            interpretation_claim(
                "Expression alone does not establish differentiation; the program can run "
                "without the culture accumulating lipid.",
                citations=_PROVENANCE,
            )
        )
    if data.is_absent(EFFICIENCY_MARKER) and data.is_present(FUNCTIONAL_MARKER):
        claims.append(
            interpretation_claim(
                "Lipid was detected but in a small fraction of the culture, so the result "
                "may reflect a subpopulation rather than the population.",
                citations=_PROVENANCE,
            )
        )
    return claims


def _conflict_explanation(
    data: AdipogenesisAssessmentInput, flags: list[AdipogenesisFlag]
) -> list[str]:
    """Why the axes disagree, naming only the readings that actually contribute.

    Domain policy, kept here on purpose: immortalization also has a conflict explanation, and
    PR14b recorded that the two decide *which* readings conflict by entirely different
    biology. Both build a ``list[str]``; nothing else is shared.
    """
    if AdipogenesisFlag.CONFLICTING_EVIDENCE not in flags:
        return []
    named = data.negative(EARLY_PROGRAM) or data.measured(EARLY_PROGRAM)
    return [
        f"Lipid accumulation is present while the commitment program ({', '.join(named)}) "
        "is not; distinguish adipogenic differentiation from lipid loading out of the medium "
        "before concluding."
    ]


def _uncertainty(
    data: AdipogenesisAssessmentInput,
    status: DifferentiationStatus,
    flags: list[AdipogenesisFlag],
) -> list[str]:
    """Caveats a reader must carry away with the verdict."""
    notes: list[str] = []
    if AdipogenesisFlag.LATE_PROGRAM_ABSENT in flags and data.within_early_induction:
        notes.append(
            f"Completion markers are absent at day {data.induction_day}; before day "
            f"{LATE_PROGRAM_EXPECTED_BY_DAY} this is the expected course rather than a failure."
        )
    if status is DifferentiationStatus.PARTIALLY_DIFFERENTIATED:
        notes.append(
            "Whether the program completes is not established by this assessment; it reports "
            "where the culture is, not where it will end."
        )
    if data.is_present(FUNCTIONAL_MARKER) and not data.has_reading(EFFICIENCY_MARKER):
        notes.append(
            "Lipid was detected but the proportion of the culture involved was not measured."
        )
    return notes


def _missing(data: AdipogenesisAssessmentInput) -> list[str]:
    """Which required axes were not measured.

    *Which* axes are required is this domain's judgement; the subtraction is the kernel's.
    """
    values: dict[str, object] = {axis: data.value(axis) for axis in REQUIRED_AXES}
    return missing_axes(REQUIRED_AXES, values)


def _validation(
    data: AdipogenesisAssessmentInput,
    status: DifferentiationStatus,
    flags: list[AdipogenesisFlag],
) -> list[str]:
    """What to verify — the axis or the goal, not the assay."""
    goals: list[str] = []
    if status in (
        DifferentiationStatus.DIFFERENTIATING,
        DifferentiationStatus.PARTIALLY_DIFFERENTIATED,
    ):
        goals.append("Independent confirmation of lipid content by a second assay")
        if AdipogenesisFlag.MATURATION_UNVERIFIED in flags:
            goals.append("Adipocyte maturity, which this assessment does not establish")
    if data.is_present(FUNCTIONAL_MARKER) and not data.has_reading(EFFICIENCY_MARKER):
        goals.append("Proportion of the culture that differentiated")
    if AdipogenesisFlag.VIABILITY_COMPROMISED in flags:
        goals.append("Culture health, before any differentiation conclusion is drawn")
    if AdipogenesisFlag.CONFLICTING_EVIDENCE in flags:
        goals.append("Whether lipid originates from differentiation or from the medium")
    if status is DifferentiationStatus.DIFFERENTIATION_INHIBITED:
        goals.append("Whether removing the inhibitory signal restores differentiation")
    return ordered_unique(goals)


def _next_experiments(
    data: AdipogenesisAssessmentInput,
    status: DifferentiationStatus,
    flags: list[AdipogenesisFlag],
    missing: list[str],
) -> list[str]:
    """Concrete assays, most-informative first.

    Ordering is the point: the list is a plan, not a menu. Whatever *blocks* a call comes
    before whatever would merely refine one.
    """
    blocking: list[str] = []
    refining: list[str] = []

    if AdipogenesisFlag.VIABILITY_COMPROMISED in flags:
        blocking.append("Viability assay (repeat differentiation on a healthy culture)")
    if AdipogenesisFlag.CONFLICTING_EVIDENCE in flags:
        blocking.append("Lipid-free control to test for medium-derived lipid loading")
    if FUNCTIONAL_MARKER in missing:
        blocking.append("Oil Red O staining or triglyceride quantification")
    if any(marker in missing for marker in MOLECULAR_MARKERS):
        blocking.append("Adipogenic qPCR panel (PPARG, CEBPA, FABP4, ADIPOQ, PLIN1)")

    if status is DifferentiationStatus.DIFFERENTIATION_INHIBITED:
        refining.append("WNT/beta-catenin pathway activity assay")
    if status is DifferentiationStatus.PARTIALLY_DIFFERENTIATED:
        refining.append("Extend induction and re-measure the completion markers")
    if status is DifferentiationStatus.DIFFERENTIATING:
        refining.append("Time-course lipid quantification to confirm the trend")
    if data.is_present(FUNCTIONAL_MARKER) and not data.has_reading(EFFICIENCY_MARKER):
        refining.append("Quantify the differentiated fraction (Nile Red / BODIPY imaging)")
    if not data.has_reading(MORPHOLOGY_MARKER):
        refining.append("Morphological scoring of lipid-droplet-bearing cells")

    return ordered_unique([*blocking, *refining])


# --- reports -------------------------------------------------------------------


def _conclusion(status: DifferentiationStatus, flags: list[AdipogenesisFlag]) -> str:
    """The headline sentence, which must say *why* it cannot tell when it cannot tell."""
    if AdipogenesisFlag.CONFLICTING_EVIDENCE in flags:
        return _CONFLICT_CONCLUSION
    if (
        AdipogenesisFlag.VIABILITY_COMPROMISED in flags
        and status is DifferentiationStatus.INSUFFICIENT_EVIDENCE
    ):
        return _COMPROMISED_CONCLUSION
    return _CONCLUSION[status]


def assess(data: AdipogenesisAssessmentInput, store: KnowledgeStore) -> AdipogenesisAssessment:
    """Assemble the adipogenesis differentiation report and its verdict."""
    if data.intent is not AdipogenesisIntent.DIFFERENTIATION_ASSESSMENT:
        raise UnsupportedAdipogenesisIntentError(
            f"the assessment builder handles differentiation_assessment, got {data.intent.value!r}"
        )

    status = _status(data)
    flags = _flags(data)
    missing = _missing(data)

    report = DecisionReport(
        conclusion=_conclusion(status, flags),
        # Not representable here; see AdipogenesisAssessment for why it travels beside
        # the report instead of being forced into another domain's vocabulary.
        candidate_status=None,
        supporting_evidence=_supporting(data, status),
        contradicting_evidence=_contradicting(data, status, flags),
        mechanistic_chain=mechanism_links(store),
        uncertainty=_uncertainty(data, status, flags),
        missing_axes=missing,
        conflict_explanation=_conflict_explanation(data, flags),
        limitations=list(_LIMITATIONS),
        overinterpretation_risk=list(_RISKS),
        recommended_validation=_validation(data, status, flags),
        next_experiment=_next_experiments(data, status, flags, missing),
    )
    validate_assertions(
        report, _FORBIDDEN, error=AdipogenesisSafetyError, context="adipogenesis report"
    )
    return AdipogenesisAssessment(report=report, status=status, flags=flags)


def mechanism_links(store: KnowledgeStore):
    """Ground the adipogenic mechanism from the graph, using the kernel unchanged."""
    return ground_links(
        store,
        _MECHANISM_SEEDS,
        all_of(targets_in(_MECHANISM_TARGETS), relations_in(_MECHANISTIC_RELATIONS)),
    )


def build_mechanism_report(
    data: AdipogenesisAssessmentInput, store: KnowledgeStore
) -> DecisionReport:
    """A mechanism-only report: how the adipogenic program works. No status."""
    if data.intent is not AdipogenesisIntent.MECHANISM_EXPLANATION:
        raise UnsupportedAdipogenesisIntentError(
            f"the mechanism builder handles mechanism_explanation, got {data.intent.value!r}"
        )

    report = DecisionReport(
        conclusion=(
            "PPARG and CEBPA drive adipogenic commitment and the transcription program that "
            "follows it, which supports lipogenesis and lipid accumulation; WNT/beta-catenin "
            "signalling restrains the same commitment, so whether a preadipocyte enters the "
            "lineage reflects the balance between them. Maturation lies downstream of "
            "differentiation and is a separate question."
        ),
        candidate_status=None,
        supporting_evidence=[
            measurement_claim(
                "PPARG and CEBPA promote the adipogenic transcription program.",
                citations=_PROVENANCE,
            ),
            measurement_claim(
                "WNT/beta-catenin signalling inhibits the adipogenic transcription program.",
                citations=_PROVENANCE,
            ),
        ],
        mechanistic_chain=mechanism_links(store),
        limitations=list(_LIMITATIONS),
        overinterpretation_risk=list(_RISKS),
    )
    validate_assertions(
        report, _FORBIDDEN, error=AdipogenesisSafetyError, context="adipogenesis mechanism report"
    )
    return report
