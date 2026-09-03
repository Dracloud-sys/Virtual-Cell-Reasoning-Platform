"""Deterministic genome-edit validation — the third vertical's report builder.

Written against the PR14a/PR14b kernel and, deliberately, not by copying either existing
vertical. Everything biological lives here; everything procedural comes from the kernel, which
is not permitted to learn any of it.

The commitments, in the order they matter:

1. **A band is not a genotype.** A PCR screen answers "did something amplify at the expected
   size". It cannot say which allele, how many, or whether the population is mixed — so a
   PCR-only result reaches no verdict in either direction.
2. **A difference needs something to differ from.** Without a matched unedited parent, even a
   sequenced result is uninterpretable.
3. **Editing is not cloning.** A mixed population is a different finding from a clone, with a
   different next step: subclone, not sequence again.
4. **A DNA edit is not a protein knockout.** Reported on every positive call, because the
   inference is the one everybody makes.
5. **Three clean sites are not a clean genome.** No amount of predicted-site screening
   supports an absence claim across a genome.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.agents.genome_editing.models import (
    REQUIRED_AXES,
    AllelePattern,
    AssayValue,
    ControlValue,
    DetectionValue,
    EditingAssessmentInput,
    EditingFlag,
    EditingIntent,
    EditStatus,
    EditType,
    ExpressionValue,
    OffTargetValue,
)
from virtualcell.core.evidence import Claim
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.decision import DecisionReport
from virtualcell.reasoning.kernel import (
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

_PROVENANCE = ["curated:genome_editing_seed"]

CAS9 = "gene:CAS9"
_MECHANISM_SEEDS = [CAS9]
_KNOCKOUT_TARGETS = {
    "mechanism:double_strand_break",
    "mechanism:nhej_repair",
    "mechanism:frameshift",
    "phenotype:loss_of_function",
}
_KNOCK_IN_TARGETS = {
    "mechanism:double_strand_break",
    "mechanism:hdr_repair",
    "mechanism:knock_in_integration",
    "phenotype:cassette_integration",
}
_MECHANISM_TARGETS = {
    EditType.KNOCKOUT: _KNOCKOUT_TARGETS,
    EditType.KNOCK_IN: _KNOCK_IN_TARGETS,
    EditType.UNKNOWN: _KNOCKOUT_TARGETS | _KNOCK_IN_TARGETS,
}
# Stated positively, as the kernel requires: only promotes/inhibits assert that one thing acts
# on another. The associated-with edges in this graph (the amplicon readout, the mosaicism
# risk) are real and deliberately *not* mechanism claims.
_MECHANISTIC_RELATIONS = {"promotes", "inhibits"}

_FORBIDDEN = (
    "knockout confirmed",
    "gene is inactivated",
    "loss of function confirmed",
    "no off-target effects",
    "off-target free",
    "clean genome",
    "safe to use",
    "functionally validated",
)

_LIMITATIONS = (
    "A confirmed edit at the DNA level does not establish that the protein is absent or that "
    "its function is lost; that requires separate protein-level and functional evidence.",
    "Off-target assessment bounded by predicted sites cannot support a claim about the genome.",
    "This assessment says nothing about whether the resulting line is safe, stable over "
    "passage, or suitable for any downstream application.",
)

_RISKS = (
    "Do not read an amplicon size shift as a genotype; a band reports that something "
    "amplified, not which allele is present.",
    "Do not read an edited clone as a functional knockout - the two are separate claims with "
    "separate evidence.",
)

_CONCLUSION = {
    EditStatus.EDITED_CLONAL: (
        "The intended edit is present and the sequenced allele pattern is consistent with a "
        "single genotype; this is an edited clone, not a validated functional outcome."
    ),
    EditStatus.EDITED_MOSAIC: (
        "The intended edit is present but the sequenced allele pattern is mixed, so this is an "
        "edited population rather than a clone."
    ),
    EditStatus.UNEDITED: (
        "Sequencing against a matched parental control found no evidence of the intended edit "
        "at the target locus."
    ),
    EditStatus.INSUFFICIENT_EVIDENCE: (
        "The available evidence does not support a call about the edit; what is missing is "
        "named below."
    ),
}
_WEAK_CONCLUSION = (
    "The locus was screened by a method that cannot read an allele, so neither the presence "
    "nor the absence of the intended edit is established; a band is not a genotype."
)
_CONTROL_CONCLUSION = (
    "No matched parental control was reported, so the observed result has nothing to be "
    "compared against and cannot support a call about the edit."
)
_CONFLICT_CONCLUSION = (
    "The screen and the independent sequence confirmation disagree about the target locus; "
    "resolve the disagreement before drawing any conclusion about the edit."
)


class EditingSafetyError(ValueError):
    """Raised when an edit report asserts a functional or safety claim it cannot support."""


class UnsupportedEditingIntentError(ValueError):
    """Raised when a builder is handed an intent it does not serve."""


class EditingAssessment(BaseModel):
    """The verdict and its report.

    The status travels beside the report for the same reason adipogenesis's does:
    ``DecisionReport.candidate_status`` is typed to immortalization's vocabulary. Recorded
    again here because a third domain hitting the same wall is the evidence that would justify
    migrating it — see the findings in `docs/genome_editing_vertical.md`.
    """

    model_config = ConfigDict(frozen=True)

    report: DecisionReport
    status: EditStatus
    flags: list[EditingFlag] = Field(default_factory=list)


# --- the deterministic verdict -------------------------------------------------


def _status(data: EditingAssessmentInput) -> EditStatus:
    """The verdict. Blocking conditions first, because each says the readings cannot be
    trusted rather than describing what the locus contains."""
    if data.conflicting:
        return EditStatus.INSUFFICIENT_EVIDENCE
    if data.parental_control is not ControlValue.MATCHED:
        return EditStatus.INSUFFICIENT_EVIDENCE
    if not data.sequence_level:
        # A band is not a genotype - in either direction. A PCR-negative is not an absence
        # call any more than a PCR-positive is a presence call.
        return EditStatus.INSUFFICIENT_EVIDENCE

    if data.edit_detected is DetectionValue.ABSENT:
        return EditStatus.UNEDITED
    if data.edit_detected is DetectionValue.PRESENT:
        if data.allele_pattern is AllelePattern.MIXED:
            return EditStatus.EDITED_MOSAIC
        if data.allele_pattern in (AllelePattern.HOMOZYGOUS, AllelePattern.HETEROZYGOUS):
            return EditStatus.EDITED_CLONAL
        # Sequenced, edit found, and nobody reported the allele pattern: clonality is exactly
        # the question that is open, so it is not answered by assumption.
        return EditStatus.INSUFFICIENT_EVIDENCE
    return EditStatus.INSUFFICIENT_EVIDENCE


def _flags(data: EditingAssessmentInput, status: EditStatus) -> list[EditingFlag]:
    flags: list[EditingFlag] = []
    if data.conflicting:
        flags.append(EditingFlag.CONFLICTING_EVIDENCE)
    if data.parental_control is not ControlValue.MATCHED:
        flags.append(EditingFlag.CONTROL_MISSING)
    if not data.sequence_level and data.edit_detected is not DetectionValue.UNKNOWN:
        # Only a *reported* screen can be weak. An unmeasured locus is a gap, not a weak read.
        flags.append(EditingFlag.WEAK_ASSAY)
    if status is EditStatus.EDITED_MOSAIC:
        flags.append(EditingFlag.MOSAIC_POPULATION)

    positive = status in (EditStatus.EDITED_CLONAL, EditStatus.EDITED_MOSAIC)
    if positive and not data.off_target_assessed:
        flags.append(EditingFlag.OFF_TARGET_UNASSESSED)
    if positive and data.protein_expression is ExpressionValue.UNKNOWN:
        flags.append(EditingFlag.FUNCTION_UNVERIFIED)
    return flags


# --- evidence ------------------------------------------------------------------

_OBSERVED_AXES: tuple[str, ...] = (
    "edit_detected",
    "edit_assay",
    "sequence_confirmed",
    "allele_pattern",
    "parental_control",
    "off_target_screened",
    "protein_expression",
    "edit_type",
)


def _observed(data: EditingAssessmentInput) -> list[Claim]:
    """What was measured, stated as measurements — never as conclusions."""
    claims: list[Claim] = []
    for axis in _OBSERVED_AXES:
        value = data.value(axis)
        if value is None or str(value) == "unknown":
            continue
        claims.append(measurement_claim(f"{axis} recorded as {value}.", citations=_PROVENANCE))
    return claims


def _supporting(data: EditingAssessmentInput, status: EditStatus) -> list[Claim]:
    claims = _observed(data)
    if status is EditStatus.EDITED_CLONAL:
        claims.append(
            interpretation_claim(
                "A sequence-level assay against a matched parental control reports the "
                "intended edit with a single allele pattern, which is consistent with an "
                "edited clone at this locus.",
                citations=_PROVENANCE,
            )
        )
    if status is EditStatus.EDITED_MOSAIC:
        claims.append(
            interpretation_claim(
                "The intended edit is present, and the mixed allele pattern indicates the "
                "population carries more than one genotype at the target locus.",
                citations=_PROVENANCE,
            )
        )
    if status is EditStatus.UNEDITED:
        claims.append(
            interpretation_claim(
                "A sequence-level assay is capable of establishing absence at this locus, so "
                "the negative result is informative rather than merely uninformative.",
                citations=_PROVENANCE,
            )
        )
    if data.off_target_screened is OffTargetValue.GENOME_WIDE:
        claims.append(
            interpretation_claim(
                "A genome-wide off-target search was performed, which bounds the unintended "
                "edit question far more tightly than a predicted-site panel.",
                citations=_PROVENANCE,
            )
        )
    if data.protein_expression is ExpressionValue.ABSENT:
        claims.append(
            interpretation_claim(
                "The target protein was not detected, which is consistent with disruption of "
                "the locus; on its own it does not establish that function is lost.",
                citations=_PROVENANCE,
            )
        )
    return claims


def _contradicting(
    data: EditingAssessmentInput, status: EditStatus, flags: list[EditingFlag]
) -> list[Claim]:
    claims: list[Claim] = []
    if EditingFlag.CONFLICTING_EVIDENCE in flags:
        claims.append(
            interpretation_claim(
                "The screen and the independent sequence confirmation report different states "
                "of the same locus; at most one of them is right.",
                citations=_PROVENANCE,
            )
        )
    if EditingFlag.WEAK_ASSAY in flags:
        claims.append(
            interpretation_claim(
                "The locus was screened by amplicon size, which reports that a product of the "
                "expected length was produced and not which allele is present.",
                citations=_PROVENANCE,
            )
        )
    if EditingFlag.CONTROL_MISSING in flags:
        claims.append(
            interpretation_claim(
                "Without a matched unedited parent, a locus result cannot be distinguished "
                "from an assay artifact or from pre-existing sequence variation.",
                citations=_PROVENANCE,
            )
        )
    if EditingFlag.MOSAIC_POPULATION in flags:
        claims.append(
            interpretation_claim(
                "A mixed population is not a clone; its genotype composition can shift under "
                "expansion, so downstream results are not attributable to a single genotype.",
                citations=_PROVENANCE,
            )
        )
    if data.off_target_screened is OffTargetValue.PREDICTED_SITES:
        claims.append(
            interpretation_claim(
                "Off-target screening covered predicted sites only, which answers a narrower "
                "question than whether the genome carries unintended edits.",
                citations=_PROVENANCE,
            )
        )
    if (
        status is EditStatus.INSUFFICIENT_EVIDENCE
        and data.edit_detected is DetectionValue.PRESENT
        and EditingFlag.CONFLICTING_EVIDENCE not in flags
    ):
        claims.append(
            interpretation_claim(
                "A positive locus result is not by itself an edit call; what the result means "
                "depends on the method that produced it and on what it was compared against.",
                citations=_PROVENANCE,
            )
        )
    return claims


def _conflict_explanation(data: EditingAssessmentInput, flags: list[EditingFlag]) -> list[str]:
    if EditingFlag.CONFLICTING_EVIDENCE not in flags:
        return []
    return [
        f"The {data.edit_assay.value} screen reports the target locus as "
        f"{data.edit_detected.value} while the independent sequence confirmation reports it as "
        f"{data.sequence_confirmed.value}; re-sequence the locus from fresh material before "
        "treating either result as the finding."
    ]


def _uncertainty(data: EditingAssessmentInput, status: EditStatus) -> list[str]:
    notes: list[str] = []
    if status is EditStatus.EDITED_CLONAL and data.allele_pattern is AllelePattern.HETEROZYGOUS:
        notes.append(
            "One allele carries the edit and one does not; whether that is sufficient depends "
            "on the intended outcome, which this assessment does not know."
        )
    if status is EditStatus.UNEDITED and data.edit_assay is AssayValue.SANGER:
        notes.append(
            "Sanger sequencing resolves a dominant allele; a low-frequency edited "
            "subpopulation can sit below its detection limit."
        )
    return notes


def _missing(data: EditingAssessmentInput) -> list[str]:
    """Which required axes were not measured. The subtraction is the kernel's."""
    values: dict[str, object] = {axis: str(data.value(axis)) for axis in REQUIRED_AXES}
    return missing_axes(REQUIRED_AXES, values, unmeasured={"unknown", "None"})


def _validation(data: EditingAssessmentInput, status: EditStatus, flags: list[EditingFlag]):
    """What to verify — the goal, not the assay."""
    goals: list[str] = []
    if EditingFlag.CONFLICTING_EVIDENCE in flags:
        goals.append("Which of the two disagreeing locus results is correct")
    if EditingFlag.CONTROL_MISSING in flags:
        goals.append("The unedited parental genotype at the same locus")
    if EditingFlag.WEAK_ASSAY in flags:
        goals.append("The allele sequence at the target locus, not only its amplicon size")
    if status is EditStatus.EDITED_MOSAIC:
        goals.append("Whether a single-genotype clone can be recovered from this population")
    if status in (EditStatus.EDITED_CLONAL, EditStatus.EDITED_MOSAIC):
        if not data.off_target_assessed:
            goals.append("Unintended edits elsewhere in the genome, which remain unassessed")
        if data.protein_expression is ExpressionValue.UNKNOWN:
            goals.append("Whether the edit changes the protein, which the DNA result does not")
    return ordered_unique(goals)


def _next_experiments(
    data: EditingAssessmentInput, status: EditStatus, flags: list[EditingFlag], missing: list[str]
) -> list[str]:
    """Concrete assays, most-informative first: whatever blocks a call before whatever
    refines one."""
    blocking: list[str] = []
    refining: list[str] = []

    if EditingFlag.CONFLICTING_EVIDENCE in flags:
        blocking.append("Re-sequence the target locus from independently prepared material")
    if EditingFlag.CONTROL_MISSING in flags:
        blocking.append("Sequence the matched parental line at the target locus")
    if EditingFlag.WEAK_ASSAY in flags or "edit_assay" in missing:
        blocking.append("Sanger sequencing of the target amplicon (or targeted NGS)")
    if "edit_detected" in missing:
        blocking.append("Screen the target locus and record the result")
    if status is EditStatus.INSUFFICIENT_EVIDENCE and data.sequence_level and not missing:
        blocking.append("Report the allele pattern from the existing sequence data")

    if status is EditStatus.EDITED_MOSAIC:
        refining.append("Single-cell cloning followed by targeted NGS of each clone")
    if status in (EditStatus.EDITED_CLONAL, EditStatus.EDITED_MOSAIC):
        if not data.off_target_assessed:
            refining.append("Genome-wide off-target screen")
        if data.protein_expression is ExpressionValue.UNKNOWN:
            refining.append(
                "Western blot for the target protein"
                if data.edit_type is not EditType.KNOCK_IN
                else "Expression assay for the integrated cassette"
            )
        if data.edit_type is EditType.KNOCK_IN:
            refining.append("Sequence both integration junctions")
    return ordered_unique([*blocking, *refining])


def _conclusion(data: EditingAssessmentInput, status: EditStatus, flags: list[EditingFlag]) -> str:
    """The headline sentence, which must say *why* it cannot tell when it cannot tell."""
    if EditingFlag.CONFLICTING_EVIDENCE in flags:
        return _CONFLICT_CONCLUSION
    if EditingFlag.CONTROL_MISSING in flags:
        return _CONTROL_CONCLUSION
    if EditingFlag.WEAK_ASSAY in flags:
        return _WEAK_CONCLUSION
    return _CONCLUSION[status]


def assess(data: EditingAssessmentInput, store: KnowledgeStore) -> EditingAssessment:
    """Assemble the edit-validation report and its verdict."""
    if data.intent is not EditingIntent.EDIT_VALIDATION:
        raise UnsupportedEditingIntentError(
            f"the assessment builder handles edit_validation, got {data.intent.value!r}"
        )

    status = _status(data)
    flags = _flags(data, status)
    missing = _missing(data)

    report = DecisionReport(
        conclusion=_conclusion(data, status, flags),
        # Not representable: the shared field carries immortalization's vocabulary. The
        # verdict travels on EditingAssessment and reaches callers on DecisionSupport.status.
        candidate_status=None,
        supporting_evidence=_supporting(data, status),
        contradicting_evidence=_contradicting(data, status, flags),
        mechanistic_chain=mechanism_links(store, data.edit_type),
        uncertainty=_uncertainty(data, status),
        missing_axes=missing,
        conflict_explanation=_conflict_explanation(data, flags),
        limitations=list(_LIMITATIONS),
        overinterpretation_risk=list(_RISKS),
        recommended_validation=_validation(data, status, flags),
        next_experiment=_next_experiments(data, status, flags, missing),
    )
    validate_assertions(report, _FORBIDDEN, error=EditingSafetyError, context="edit report")
    return EditingAssessment(report=report, status=status, flags=flags)


def mechanism_links(store: KnowledgeStore, edit_type: EditType = EditType.UNKNOWN):
    """Ground the editing mechanism from the graph, using the kernel unchanged.

    The target allowlist is chosen by edit type, so a knockout question does not ground a
    knock-in chain. The amplicon readout is excluded by the relation filter rather than by the
    target filter, which is the point: it is a real edge and not a mechanism claim.
    """
    return ground_links(
        store,
        _MECHANISM_SEEDS,
        all_of(
            targets_in(_MECHANISM_TARGETS[edit_type]),
            relations_in(_MECHANISTIC_RELATIONS),
        ),
    )


def build_mechanism_report(data: EditingAssessmentInput, store: KnowledgeStore) -> DecisionReport:
    """A mechanism-only report: how an edit becomes an outcome. No status."""
    if data.intent is not EditingIntent.MECHANISM_EXPLANATION:
        raise UnsupportedEditingIntentError(
            f"the mechanism builder handles mechanism_explanation, got {data.intent.value!r}"
        )

    report = DecisionReport(
        conclusion=(
            "A targeted nuclease produces a double-strand break, and which repair pathway "
            "resolves it decides the outcome: non-homologous end joining leaves indels that "
            "may disrupt the reading frame, while homology-directed repair integrates a "
            "supplied template. The break also provokes a damage response, which restrains "
            "the template-dependent route. What ends up at the locus is therefore a property "
            "of repair, not of cutting."
        ),
        candidate_status=None,
        supporting_evidence=[
            measurement_claim(
                "A targeted nuclease introduces a double-strand break at the intended locus.",
                citations=_PROVENANCE,
            ),
            interpretation_claim(
                "Non-homologous end joining is error-prone, so indels - and sometimes "
                "frameshifts - are its expected products.",
                citations=_PROVENANCE,
            ),
            interpretation_claim(
                "Homology-directed repair requires a template and competes with end joining, "
                "which is why knock-in efficiencies are typically the lower of the two.",
                citations=_PROVENANCE,
            ),
        ],
        contradicting_evidence=[],
        mechanistic_chain=mechanism_links(store, data.edit_type),
        limitations=list(_LIMITATIONS),
        overinterpretation_risk=list(_RISKS),
        recommended_validation=[
            "The allele actually produced at the target locus",
            "Whether the population carries one genotype or several",
            "Unintended edits elsewhere in the genome",
        ],
        next_experiment=[
            "Sanger sequencing of the target amplicon (or targeted NGS)",
            "Single-cell cloning followed by targeted NGS of each clone",
            "Genome-wide off-target screen",
        ],
    )
    validate_assertions(report, _FORBIDDEN, error=EditingSafetyError, context="mechanism report")
    return report
