"""Genome-editing domain pack — the third vertical behind the PR11 boundary.

A thin adapter, like the other two: it maps a generic
:class:`~virtualcell.platform.contracts.ReasoningQuery` onto the vertical's own builders and
converts the resulting report into the generic envelope. It contains **no** scientific rules.

It is also the milestone's actual claim. Adding this domain required **one** line in the
composition root and **zero** changes to the reasoning kernel — which is the evidence the
first two verticals could not provide, having been written by people who had just read each
other.

The declaration below is the single source of truth for this domain's axes. The description a
caller reads and the consumption ledger a response carries are both derived from it, so a pack
cannot advertise one thing and report another.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from virtualcell.agents.genome_editing.assessment import (
    EditingAssessment,
    assess,
    build_mechanism_report,
)
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
from virtualcell.core.consumption import ConsumptionReport
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.contracts import (
    DecisionSupport,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.description import (
    AxisDescription,
    AxisKind,
    DomainDescription,
    MissingInput,
    TaskDescription,
    ValueType,
    derive_consumption,
    resolve_missing_inputs,
)
from virtualcell.platform.domains import QueryValidationError
from virtualcell.reasoning.decision import DecisionReport

DOMAIN = "genome_editing"
PACK_ID = "genome_editing.v1"
ENGINE = "genome_edit_validation"

TASK_ASSESS = "assess_state"
TASK_MECHANISM = "explain_mechanism"

_TASK_INTENT = {
    TASK_ASSESS: EditingIntent.EDIT_VALIDATION,
    TASK_MECHANISM: EditingIntent.MECHANISM_EXPLANATION,
}

_STATUS = "edit_status"
_UNKNOWN = "unknown"


def _vocab(enum) -> tuple[str, ...]:
    """Take the accepted values from the enum the model validates against.

    Not a second list: if a value is added to the enum it appears in the description
    automatically, and a description that named its own vocabulary would be free to drift
    from what the input actually accepts.
    """
    return tuple(member.value for member in enum)


_AXES: tuple[AxisDescription, ...] = (
    AxisDescription(
        name="edit_detected",
        description=(
            "What the screen found at the target locus. 'absent' is a result; 'unknown' is a "
            "gap, and the two are not interchangeable."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(DetectionValue),
        kind=AxisKind.STATUS,
        required=True,
        unmeasured_value=_UNKNOWN,
        used_for=(_STATUS, "evidence"),
    ),
    AxisDescription(
        name="edit_assay",
        description=(
            "How the locus was screened. This decides what the result can mean at all: 'pcr' "
            "reports an amplicon size, while 'sanger' and 'ngs' read the allele. A band is "
            "not a genotype, in either direction."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(AssayValue),
        kind=AxisKind.STATUS,
        required=True,
        unmeasured_value=_UNKNOWN,
        used_for=(_STATUS, "flag:weak_assay", "evidence"),
    ),
    AxisDescription(
        name="parental_control",
        description=(
            "Whether a matched unedited parent was sequenced alongside. Without one, a locus "
            "result has nothing to differ from."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(ControlValue),
        kind=AxisKind.STATUS,
        required=True,
        unmeasured_value=_UNKNOWN,
        used_for=(_STATUS, "flag:control_missing", "evidence"),
    ),
    AxisDescription(
        name="allele_pattern",
        description=(
            "What the sequence says about the population. Decides clonal from mosaic, and is "
            "deliberately not required: it is only answerable once an edit was found, so "
            "requiring it would report a false gap on every genuinely unedited clone."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(AllelePattern),
        kind=AxisKind.STATUS,
        unmeasured_value=_UNKNOWN,
        used_for=(_STATUS, "flag:mosaic_population", "evidence"),
    ),
    AxisDescription(
        name="sequence_confirmed",
        description=(
            "An independent sequence-level confirmation of the same locus. Present so that a "
            "screen and a confirmation can be seen to disagree rather than silently averaged."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(DetectionValue),
        kind=AxisKind.STATUS,
        unmeasured_value=_UNKNOWN,
        used_for=(_STATUS, "flag:conflicting_evidence", "conflict_explanation"),
    ),
    AxisDescription(
        name="off_target_screened",
        description=(
            "How far anyone looked for unintended edits. Never changes the edit call; it "
            "changes the risk statement and the plan. 'predicted_sites' is real work that "
            "answers a narrower question than the genome, so it does not clear the flag."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(OffTargetValue),
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=(
            "flag:off_target_unassessed",
            "evidence",
            "recommended_validation",
            "next_experiment",
        ),
    ),
    AxisDescription(
        name="protein_expression",
        description=(
            "Protein-level observation. 'absent' is a real reading and is reported as "
            "evidence; it still does not establish that function is lost."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(ExpressionValue),
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=(
            "flag:function_unverified",
            "evidence",
            "recommended_validation",
            "next_experiment",
        ),
    ),
    AxisDescription(
        name="edit_type",
        description=(
            "Which edit was attempted. Selects the mechanism chain, and chooses what still "
            "needs confirming - a knock-in junction and a frameshift are different follow-ups."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_vocab(EditType),
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=("mechanistic_chain", "recommended_validation", "next_experiment"),
    ),
    AxisDescription(
        name="target_gene",
        description="The gene being edited. Recorded for provenance; no rule reads it.",
        value_type=ValueType.TEXT,
        kind=AxisKind.CONTEXT,
    ),
    AxisDescription(
        name="species",
        description="Recorded for provenance; no rule reads it.",
        value_type=ValueType.TEXT,
        kind=AxisKind.CONTEXT,
    ),
    AxisDescription(
        name="cell_type",
        description="Recorded for provenance; no rule reads it.",
        value_type=ValueType.TEXT,
        kind=AxisKind.CONTEXT,
    ),
)

DESCRIPTION = DomainDescription(
    domain=DOMAIN,
    summary=(
        "Decides whether a clone carries an intended genome edit, and how far that claim "
        "reaches. It judges the edit at the DNA level only: it will not say a gene is "
        "inactivated, that a genome is free of unintended edits, or that a line is safe to "
        "use, because no assay it models can establish any of those."
    ),
    tasks=(
        TaskDescription(
            name=TASK_ASSESS,
            purpose="judges whether a clone carries the intended edit, from measured locus data",
            required_axes=REQUIRED_AXES,
            example={
                "edit_detected": "present",
                "edit_assay": "ngs",
                "allele_pattern": "homozygous",
                "parental_control": "matched",
            },
        ),
        TaskDescription(
            name=TASK_MECHANISM,
            purpose=(
                "explains how a targeted break becomes an outcome, from the curated graph; it "
                "reads the edit type and no measured value"
            ),
            reads_axes=("edit_type",),
            example={"edit_type": "knockout"},
        ),
    ),
    axes=_AXES,
    status_vocabulary=_vocab(EditStatus),
    flags=_vocab(EditingFlag),
)


class GenomeEditingDomainPack:
    """Connects the genome-editing vertical to the generic query boundary."""

    domain = DOMAIN
    supported_tasks: tuple[str, ...] = (TASK_ASSESS, TASK_MECHANISM)

    def describe(self) -> DomainDescription:
        return DESCRIPTION

    def validate_experiment(self, task: str, experiment: Mapping[str, Any]) -> None:
        """Run this domain's real input validation and discard the result.

        The same call ``execute`` makes, so a description checked against it is checked
        against production and not against a second, more forgiving copy.
        """
        self._to_input(ReasoningQuery(domain=self.domain, task=task, experiment=dict(experiment)))

    def execute(self, query: ReasoningQuery, store: KnowledgeStore) -> ReasoningResponse:
        data = self._to_input(query)
        if query.task == TASK_MECHANISM:
            report = build_mechanism_report(data, store)
            response = self._to_response(query, report, DecisionSupport())
        else:
            outcome = assess(data, store)
            report = outcome.report
            response = self._to_response(query, report, self._decision_support(outcome))
        response.measurement_consumption = self._consumption(query, data)
        response.missing_inputs = self._missing_inputs(query, report)
        return response

    def _missing_inputs(self, query: ReasoningQuery, report) -> list[MissingInput]:
        """Resolve the native report's missing axes into keys a caller can send.

        Only ``missing_axes``. Validation goals and next experiments stay in their own
        response fields, where each says one thing; copying them here would make a caller
        filter a list named "missing inputs" before it could use any of it.

        The resolution happens *here*, at the conversion boundary, using this domain's own
        declaration - not by normalising strings in the platform. Every axis here is already
        spelled as its own key, so the resolution is an identity; doing it through the
        declaration anyway keeps it correct if a display label is ever introduced.
        """
        return resolve_missing_inputs(DESCRIPTION, task=query.task, missing=report.missing_axes)

    # --- request adaptation --------------------------------------------------

    def _to_input(self, query: ReasoningQuery) -> EditingAssessmentInput:
        experiment = dict(query.experiment)
        declared = experiment.pop("intent", None)
        expected = _TASK_INTENT[query.task]
        if declared is not None and declared != expected.value:
            raise QueryValidationError(
                f"task {query.task!r} implies intent {expected.value!r}, but the experiment "
                f"payload declares {declared!r}"
            )
        known = set(EditingAssessmentInput.model_fields)
        typed = {key: value for key, value in experiment.items() if key in known}
        extras = {key: str(value) for key, value in experiment.items() if key not in known}
        try:
            return EditingAssessmentInput(intent=expected, measurements=extras, **typed)
        except (ValidationError, ValueError) as exc:
            raise QueryValidationError(f"invalid genome-editing experiment payload: {exc}") from exc

    # --- measurement consumption (derived from the declaration) --------------

    def _consumption(
        self, query: ReasoningQuery, data: EditingAssessmentInput
    ) -> ConsumptionReport:
        return derive_consumption(
            DESCRIPTION,
            task=query.task,
            experiment=query.experiment,
            has_reading=lambda axis: str(data.value(axis.name)) not in (_UNKNOWN, "None", ""),
        )

    # --- response conversion (normalise; never reinterpret) ------------------

    @staticmethod
    def _decision_support(outcome: EditingAssessment) -> DecisionSupport:
        flags = [flag.value for flag in outcome.flags]
        return DecisionSupport(
            status=outcome.status.value,
            flags=flags,
            # "Screened by a method that cannot read an allele" is precisely the case where
            # one more measurement of the same kind will not help, so it maps onto the
            # envelope's signal that a different reading is required.
            trend_required=EditingFlag.WEAK_ASSAY.value in flags,
        )

    def _to_response(
        self, query: ReasoningQuery, report: DecisionReport, support: DecisionSupport
    ) -> ReasoningResponse:
        return ReasoningResponse(
            domain=self.domain,
            task=query.task,
            summary=report.conclusion,
            observations=[
                claim.statement
                for claim in report.supporting_evidence
                if " recorded as " in claim.statement
            ],
            quality_findings=[],
            interpretations=list(report.conflict_explanation),
            hypotheses=[],
            supporting_evidence=[c.model_copy(deep=True) for c in report.supporting_evidence],
            contradicting_evidence=[c.model_copy(deep=True) for c in report.contradicting_evidence],
            mechanistic_links=[link.model_copy(deep=True) for link in report.mechanistic_chain],
            missing_information=list(report.missing_axes),
            uncertainties=list(report.uncertainty),
            limitations=list(report.limitations),
            overinterpretation_risks=list(report.overinterpretation_risk),
            decision_support=support,
            recommended_validation=list(report.recommended_validation),
            recommended_next_experiments=list(report.next_experiment),
            provenance=QueryProvenance(
                domain=self.domain,
                task=query.task,
                pack=PACK_ID,
                engine=ENGINE,
                explanation_level=query.explanation_level,
                literature_requested=query.allow_literature,
                deterministic=True,
            ),
            domain_details={"decision_report": report.model_dump(mode="json")},
        )
