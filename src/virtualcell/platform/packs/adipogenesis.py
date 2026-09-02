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

from pydantic import ValidationError

from virtualcell.agents.adipogenesis.assessment import (
    AdipogenesisAssessment,
    assess,
    build_mechanism_report,
)
from virtualcell.agents.adipogenesis.models import (
    EFFICIENCY_MARKER,
    INHIBITOR_MARKERS,
    MORPHOLOGY_MARKER,
    REQUIRED_AXES,
    VIABILITY_MARKER,
    AdipogenesisAssessmentInput,
    AdipogenesisFlag,
    AdipogenesisIntent,
)
from virtualcell.core.consumption import ConsumptionLedger, ConsumptionReport
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.contracts import (
    DecisionSupport,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
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

# --- measurement-consumption policy -------------------------------------------
#
# A declaration of which purpose reads which axis, and nothing about what a value means.
#
# Worth comparing against the immortalization pack, because the split lands in a different
# place: there, *every* axis that raises a flag is guidance. Here, inhibition and viability
# genuinely gate the verdict - an active inhibitor reaches `differentiation_inhibited`, and
# a failing culture withholds the negative call - so they are status axes. Only efficiency
# and morphology refine a call they can never make. That difference is the science, and it
# is why this declaration lives in the pack rather than in the platform.

_STATUS_AXES: tuple[str, ...] = (
    *REQUIRED_AXES,
    *INHIBITOR_MARKERS,
    VIABILITY_MARKER,
    "induction_day",
)
_STATUS_PURPOSES = ["differentiation_status", "evidence"]

_GUIDANCE_AXES: dict[str, list[str]] = {
    EFFICIENCY_MARKER: ["evidence", "uncertainty", "recommended_validation", "next_experiment"],
    MORPHOLOGY_MARKER: ["evidence", "next_experiment"],
}

_CONTEXT_ONLY = ("species", "cell_type")
_CONTEXT_REASON = (
    "carried as request context and preserved in the response, but no rule in this "
    "vertical reads it"
)
_NO_READING = (None, "unknown", "")
_UNMEASURED_REASON = (
    "submitted without a reading ('unknown'), so there was nothing to consult; it is "
    "reported as a missing axis rather than as a value"
)
_MECHANISM_REASON = (
    "'explain_mechanism' explains the adipogenic program from the curated graph; it reads "
    "no measured value"
)
_UNSUPPORTED_REASON = (
    "the adipogenesis vertical has no axis with this name; the value is preserved on the "
    "assessment input but reaches no reasoning"
)


class AdipogenesisDomainPack:
    """Connects the adipogenesis vertical to the generic query boundary."""

    domain = DOMAIN
    supported_tasks: tuple[str, ...] = (TASK_ASSESS, TASK_MECHANISM)

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

    # --- measurement consumption (declaration only; nothing is re-derived) ----

    def _consumption(
        self, query: ReasoningQuery, data: AdipogenesisAssessmentInput
    ) -> ConsumptionReport:
        """What the reasoning did with each key the caller submitted.

        A reading of ``absent`` or ``low`` is a *result*, and is reported as consumed:
        "we looked and it was not there" is the finding half this vertical exists to keep
        separate from "we did not look". Only ``unknown`` lands in ``not_applicable``.
        """
        ledger = ConsumptionLedger(provenance="query.experiment")
        mechanism = query.task == TASK_MECHANISM

        for key in query.experiment:
            if key == "intent":
                continue
            if key in _CONTEXT_ONLY:
                ledger.not_applicable(key, reason=_CONTEXT_REASON)
            elif mechanism:
                ledger.not_applicable(key, reason=_MECHANISM_REASON)
            elif key in _STATUS_AXES:
                self._record_axis(ledger, key, data, _STATUS_PURPOSES, status=True)
            elif key in _GUIDANCE_AXES:
                self._record_axis(ledger, key, data, _GUIDANCE_AXES[key], status=False)
            else:
                ledger.unsupported(key, reason=_UNSUPPORTED_REASON)
        return ledger.report()

    @staticmethod
    def _record_axis(
        ledger: ConsumptionLedger,
        key: str,
        data: AdipogenesisAssessmentInput,
        purposes: list[str],
        *,
        status: bool,
    ) -> None:
        if getattr(data, key, None) in _NO_READING:
            ledger.not_applicable(key, reason=_UNMEASURED_REASON)
        elif status:
            ledger.used_for_status(key, used_for=purposes)
        else:
            ledger.used_for_guidance(key, used_for=purposes)

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
