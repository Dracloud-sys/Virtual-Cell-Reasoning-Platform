"""Deterministic adipogenesis assessment — the second vertical's report builder.

Written against the PR14a kernel and, deliberately, *not* by copying
``agents/immortalization/rules.py``. The point of a second vertical at this stage is to be
an independent second implementation, so that the comparison feeding PR14b shows what is
genuinely shared rather than what was duplicated on purpose.

The one scientific commitment worth stating plainly: **a marker panel is not a fat cell.**
The PPARG/CEBPA program running says the cell is trying; lipid in the cell says it
succeeded. A status of ``differentiating`` therefore requires the functional axis, and a
molecular-only panel is reported as insufficient with the missing measurement named. That
is the adipogenesis analogue of the immortalization rule that a proliferation signal alone
never confirms a candidate without a measured senescence axis — which is itself a hint
about what PR14b may find shared.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.agents.adipogenesis.models import (
    FUNCTIONAL_MARKER,
    INHIBITOR_MARKERS,
    MOLECULAR_MARKERS,
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
    LIPID_LADEN,
    LIPOGENESIS,
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

# This pack's judgement about which relations may carry a mechanism claim — the same
# reasoning the immortalization pack makes, stated separately because it is biology.
_MECHANISTIC_RELATIONS = (RelationType.PROMOTES, RelationType.INHIBITS)

_MECHANISM_SEEDS = [PPARG, CEBPA, WNT10B]
_MECHANISM_TARGETS = {
    PROGRAM,
    LIPOGENESIS,
    LIPID_LADEN,
    ADIPOCYTE,
    WNT_SIGNALLING,
    UNDIFFERENTIATED,
}

# Phrasings this domain must never *assert*. Each is a real way to overclaim from a marker
# panel, and each is named in the report's own guidance — which is exactly why the kernel's
# assertion scope excludes the guidance fields from the check.
_FORBIDDEN = (
    "mature adipocyte",
    "fully differentiated",
    "transdifferentiation",
    "proves the cells are fat",
    "suitable for consumption",
    "food safe",
)

_CONCLUSION = {
    DifferentiationStatus.DIFFERENTIATING: (
        "The adipogenic program is expressed and the culture has accumulated lipid, which "
        "together support ongoing adipogenic differentiation."
    ),
    DifferentiationStatus.NOT_DIFFERENTIATING: (
        "Neither the adipogenic transcription program nor lipid accumulation is detected; "
        "the culture does not appear to be differentiating under these conditions."
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
    not a preference. ``DecisionReport.candidate_status`` is typed to
    :class:`~virtualcell.reasoning.decision.CandidateStatus` — ``possible_candidate`` /
    ``senescence_or_stress_prone`` / ``insufficient_evidence`` — which is immortalization's
    vocabulary, and there is no honest way to say "differentiating" in it. Borrowing
    ``possible_candidate`` to mean "differentiating" would make two domains' statuses
    indistinguishable to every reader downstream.

    So the shared report contract currently carries the first vertical's status vocabulary,
    and a second vertical has to wrap it. That is recorded here for the assembly comparison
    rather than fixed in passing: whether the field should become domain-neutral, or move
    out of the report entirely, is a PR14b decision that wants both implementations in view.
    """

    model_config = ConfigDict(extra="forbid")

    report: DecisionReport
    status: DifferentiationStatus
    flags: list[AdipogenesisFlag] = Field(default_factory=list)


class UnsupportedAdipogenesisIntentError(ValueError):
    """Raised when this builder is asked to answer something it does not handle."""


class AdipogenesisSafetyError(AssertionSafetyError):
    """Raised when an adipogenesis report asserts a forbidden overclaim."""


def _status(
    data: AdipogenesisAssessmentInput,
) -> tuple[DifferentiationStatus, list[AdipogenesisFlag]]:
    """The deterministic verdict. No graph, no model — a stable regression anchor."""
    flags: list[AdipogenesisFlag] = []
    molecular_positive = data.positive(MOLECULAR_MARKERS)
    molecular_measured = data.measured(MOLECULAR_MARKERS)
    lipid = data.value(FUNCTIONAL_MARKER)
    inhibitors_active = data.positive(INHIBITOR_MARKERS)

    if inhibitors_active:
        flags.append(AdipogenesisFlag.INHIBITOR_ACTIVE)
    if lipid in (None, "unknown"):
        flags.append(AdipogenesisFlag.FUNCTION_UNMEASURED)
    if 0 < len(molecular_measured) < len(MOLECULAR_MARKERS):
        flags.append(AdipogenesisFlag.MARKERS_INCOMPLETE)

    lipid_present = lipid == "high"
    lipid_absent = lipid in ("low", "absent")

    # A marker panel is not a fat cell: the functional axis is required in both directions.
    if molecular_positive and lipid_present:
        return DifferentiationStatus.DIFFERENTIATING, flags
    if inhibitors_active and not molecular_positive:
        return DifferentiationStatus.DIFFERENTIATION_INHIBITED, flags
    if molecular_measured and not molecular_positive and lipid_absent:
        return DifferentiationStatus.NOT_DIFFERENTIATING, flags
    return DifferentiationStatus.INSUFFICIENT_EVIDENCE, flags


def _observed(data: AdipogenesisAssessmentInput) -> list[Claim]:
    """What was measured, stated as measurements — never as conclusions."""
    claims: list[Claim] = []
    for marker in (*MOLECULAR_MARKERS, FUNCTIONAL_MARKER, *INHIBITOR_MARKERS):
        value = data.value(marker)
        if value in (None, "unknown"):
            continue
        claims.append(measurement_claim(f"{marker} measured as {value}.", citations=_PROVENANCE))
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
    if status is DifferentiationStatus.INSUFFICIENT_EVIDENCE and data.positive(MOLECULAR_MARKERS):
        claims.append(
            interpretation_claim(
                "Expression alone does not establish differentiation; the program can run "
                "without the culture accumulating lipid.",
                citations=_PROVENANCE,
            )
        )
    return claims


def _missing(data: AdipogenesisAssessmentInput) -> list[str]:
    """Which axes were not measured — the molecular panel and the functional one.

    Both groups go through the same kernel subtraction; that this domain requires *two*
    kinds of axis, and that the functional one is not optional, is its own judgement.
    """
    required = (*MOLECULAR_MARKERS, FUNCTIONAL_MARKER)
    values: dict[str, object] = {axis: data.value(axis) for axis in required}
    return missing_axes(required, values)


def _next_experiments(status: DifferentiationStatus, missing: list[str]) -> list[str]:
    experiments: list[str] = []
    if FUNCTIONAL_MARKER in missing:
        experiments.append("Oil Red O staining or triglyceride quantification")
    if any(m in missing for m in MOLECULAR_MARKERS):
        experiments.append("Adipogenic qPCR panel (PPARG, CEBPA, FABP4, ADIPOQ)")
    if status is DifferentiationStatus.DIFFERENTIATION_INHIBITED:
        experiments.append("WNT/beta-catenin pathway activity assay")
    if status is DifferentiationStatus.DIFFERENTIATING:
        experiments.append("Time-course lipid quantification to confirm the trend")
    return ordered_unique(experiments)


def assess(data: AdipogenesisAssessmentInput, store: KnowledgeStore) -> AdipogenesisAssessment:
    """Assemble the adipogenesis differentiation report and its verdict."""
    if data.intent is not AdipogenesisIntent.DIFFERENTIATION_ASSESSMENT:
        raise UnsupportedAdipogenesisIntentError(
            f"the assessment builder handles differentiation_assessment, got {data.intent.value!r}"
        )

    status, flags = _status(data)
    missing = _missing(data)
    report = DecisionReport(
        conclusion=_CONCLUSION[status],
        # Not representable here; see AdipogenesisAssessment for why it travels beside
        # the report instead of being forced into another domain's vocabulary.
        candidate_status=None,
        supporting_evidence=_supporting(data, status),
        contradicting_evidence=_contradicting(data, status, flags),
        mechanistic_chain=mechanism_links(store),
        missing_axes=missing,
        limitations=list(_LIMITATIONS),
        overinterpretation_risk=list(_RISKS),
        recommended_validation=["Independent confirmation of lipid content by a second assay"],
        next_experiment=_next_experiments(status, missing),
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
            "PPARG and CEBPA drive the adipogenic transcription program, which supports "
            "lipogenesis and lipid accumulation; WNT/beta-catenin signalling restrains the "
            "same program, so commitment reflects the balance between them."
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
