"""Adipogenesis domain pack — the second vertical behind the PR11 boundary.

A thin adapter, like the immortalization pack: it maps a generic
:class:`~virtualcell.platform.contracts.ReasoningQuery` onto the vertical's own builders and
converts the resulting report into the generic envelope. It contains **no** scientific
rules — no thresholds, no status derivation, no claim construction.

This pack is also the proof of the PR11 claim: **one declaration** in the composition root
(a :class:`~virtualcell.platform.bootstrap.ShippedDomain` naming this pack and its seed
source) made ``{"domain": "adipogenesis", "task": ...}`` both answerable and grounded, with
no API route, CLI command, request contract or service change.

One place it differs from the immortalization pack, and the difference is a finding rather
than a style choice: the vertical's status cannot ride on ``DecisionReport.candidate_status``
(whose vocabulary is immortalization's), so it arrives beside the report and this pack puts
it on ``DecisionSupport.status`` — which *is* domain-neutral. The platform envelope was
already general enough; the report contract was not.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from virtualcell.agents.adipogenesis.assessment import (
    AdipogenesisAssessment,
    assess,
    build_mechanism_report,
)
from virtualcell.agents.adipogenesis.models import (
    AdipogenesisAssessmentInput,
    AdipogenesisFlag,
    AdipogenesisIntent,
    DifferentiationStatus,
    MarkerValue,
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
    TaskDescription,
    ValueType,
    derive_consumption,
)
from virtualcell.platform.domains import QueryValidationError
from virtualcell.reasoning.decision import DecisionReport

DOMAIN = "adipogenesis"
# Kept at ".minimal.v1" deliberately. This string is not a description of the vertical -
# it ships on every response as `provenance.pack`, so anything already keying off it (stored
# reports, downstream filters) reads a rename as a different pack. Renaming it is a
# provenance-policy change with its own migration, not a side effect of expanding a domain.
PACK_ID = "adipogenesis.minimal.v1"
ENGINE = "adipogenesis_assessment"

TASK_ASSESS = "assess_state"
TASK_MECHANISM = "explain_mechanism"

_TASK_INTENT = {
    TASK_ASSESS: AdipogenesisIntent.DIFFERENTIATION_ASSESSMENT,
    TASK_MECHANISM: AdipogenesisIntent.MECHANISM_EXPLANATION,
}

# --- axis declaration: one statement, read by both the description and the ledger ---
#
# Worth comparing against the immortalization pack, because the status/guidance split lands
# somewhere else entirely. There, every flag-raising axis is guidance. Here, inhibition and
# viability genuinely gate the verdict - an active inhibitor reaches `differentiation_inhibited`
# and a failing culture withholds the negative call - so they are status axes. Only efficiency
# and morphology refine a call they can never make.
#
# That difference is the science, and it is why this declaration lives in the pack rather than
# in the platform.

# Taken from the enum the model validates against, not restated: a second list would be
# free to drift from what the input actually accepts, which is the failure this whole
# contract exists to prevent.
_MARKER_VOCAB = tuple(v.value for v in MarkerValue)
_STATUS_PURPOSES = ("differentiation_status", "evidence")
_UNKNOWN = "unknown"


def _marker(name: str, description: str, *, required: bool = False) -> AxisDescription:
    return AxisDescription(
        name=name,
        description=description,
        value_type=ValueType.CATEGORICAL,
        vocabulary=_MARKER_VOCAB,
        kind=AxisKind.STATUS,
        required=required,
        unmeasured_value=_UNKNOWN,
        used_for=_STATUS_PURPOSES,
    )


_AXES: tuple[AxisDescription, ...] = (
    _marker("PPARG", "Master adipogenic regulator; commitment.", required=True),
    _marker("CEBPA", "Commitment regulator, with PPARG.", required=True),
    _marker("FABP4", "Completion marker.", required=True),
    _marker("ADIPOQ", "Completion and maturation marker.", required=True),
    _marker("PLIN1", "Completion and maturation marker; droplet coat.", required=True),
    _marker(
        "lipid_accumulation",
        "The functional axis. A marker panel says the program is running; this says the cell "
        "actually stored lipid, and a positive call requires it.",
        required=True,
    ),
    _marker(
        "WNT_signalling",
        "Inhibitory signal. Gates the verdict: an active inhibitor with no program reaches "
        "differentiation_inhibited, which is a different finding from unresponsive.",
    ),
    _marker("DLK1", "Inhibitory signal (PREF-1)."),
    _marker(
        "viability",
        "Culture health. Blocks the *negative* call - dying and not-differentiating look "
        "identical on a panel and have different fixes - and never the positive one.",
    ),
    AxisDescription(
        name="induction_day",
        description=(
            "Days since induction. A modifier, not a series: it changes what absent completion "
            "markers mean. Only a stated early day withholds a failure call; silence "
            "manufactures no doubt."
        ),
        value_type=ValueType.INTEGER,
        minimum=0,
        kind=AxisKind.STATUS,
        used_for=_STATUS_PURPOSES,
    ),
    AxisDescription(
        name="lipid_efficiency",
        description=(
            "What proportion of the culture accumulated lipid. 5% and 80% are different "
            "results, and neither changes whether differentiation happened."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_MARKER_VOCAB,
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=("evidence", "uncertainty", "recommended_validation", "next_experiment"),
    ),
    AxisDescription(
        name="morphology",
        description=(
            "Rounded, droplet-bearing cells. Corroborating only: a photograph is not an assay, "
            "so it supports a call and can never make one."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=_MARKER_VOCAB,
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=("evidence", "next_experiment"),
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
        "Judges how far an adipogenic differentiation program has run, from transcriptional "
        "and functional readings. It reports that a program is running or complete; it never "
        "reports a mature adipocyte, and says nothing about whether the result is safe or "
        "edible."
    ),
    tasks=(
        TaskDescription(
            name=TASK_ASSESS,
            purpose="judges differentiation from measured markers and lipid content",
            required_axes=tuple(a.name for a in _AXES if a.required),
            example={
                "PPARG": "high",
                "CEBPA": "high",
                "FABP4": "high",
                "lipid_accumulation": "high",
            },
        ),
        TaskDescription(
            name=TASK_MECHANISM,
            purpose=(
                "explains the adipogenic program from the curated graph; it reads no measured value"
            ),
            reads_measurements=False,
        ),
    ),
    axes=_AXES,
    status_vocabulary=tuple(v.value for v in DifferentiationStatus),
    flags=tuple(v.value for v in AdipogenesisFlag),
)


class AdipogenesisDomainPack:
    """Connects the adipogenesis vertical to the generic query boundary."""

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
            response = self._to_response(query, outcome.report, self._decision_support(outcome))
        response.measurement_consumption = self._consumption(query, data)
        return response

    # --- measurement consumption (derived from the declaration above) --------

    def _consumption(
        self, query: ReasoningQuery, data: AdipogenesisAssessmentInput
    ) -> ConsumptionReport:
        """A reading of ``absent`` or ``low`` is a *result* and is reported as consumed: "we
        looked and it was not there" is the finding half this vertical exists to keep separate
        from "we did not look". Only ``unknown`` lands in ``not_applicable``."""
        return derive_consumption(
            DESCRIPTION,
            task=query.task,
            experiment=query.experiment,
            has_reading=lambda axis: getattr(data, axis.name, None) not in (None, _UNKNOWN, ""),
        )

    # --- request adaptation --------------------------------------------------

    def _to_input(self, query: ReasoningQuery) -> AdipogenesisAssessmentInput:
        experiment = dict(query.experiment)
        declared = experiment.pop("intent", None)
        expected = _TASK_INTENT[query.task]
        # A task names one intent, so a contradicting payload would answer a different
        # question than the caller selected. Refuse rather than pick a winner.
        if declared is not None and declared != expected.value:
            raise QueryValidationError(
                f"task {query.task!r} implies intent {expected.value!r}, but the experiment "
                f"payload declares {declared!r}"
            )
        known = set(AdipogenesisAssessmentInput.model_fields)
        typed = {key: value for key, value in experiment.items() if key in known}
        extras = {key: str(value) for key, value in experiment.items() if key not in known}
        try:
            return AdipogenesisAssessmentInput(intent=expected, measurements=extras, **typed)
        except (ValidationError, ValueError) as exc:
            raise QueryValidationError(f"invalid adipogenesis experiment payload: {exc}") from exc

    # --- response conversion (normalise; never reinterpret) ------------------

    @staticmethod
    def _decision_support(outcome: AdipogenesisAssessment) -> DecisionSupport:
        flags = [flag.value for flag in outcome.flags]
        return DecisionSupport(
            status=outcome.status.value,
            flags=flags,
            # "The program was read but nothing measured lipid" is precisely the case where
            # a snapshot is not enough, so it maps onto the envelope's trend signal.
            trend_required=AdipogenesisFlag.FUNCTION_UNMEASURED.value in flags,
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
                if claim.statement.endswith(".") and " measured as " in claim.statement
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
            # The native report is preserved verbatim so nothing is lost at the boundary.
            domain_details={"decision_report": report.model_dump(mode="json")},
        )
