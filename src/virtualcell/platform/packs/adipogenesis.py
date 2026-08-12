"""Adipogenesis domain pack — the second vertical behind the PR11 boundary.

A thin adapter, like the immortalization pack: it maps a generic
:class:`~virtualcell.platform.contracts.ReasoningQuery` onto the vertical's own builders and
converts the resulting report into the generic envelope. It contains **no** scientific
rules — no thresholds, no status derivation, no claim construction.

This pack is also the proof of the PR11 claim that adding a domain is a one-line change in
the composition root: no API route, CLI command, request contract or service change was
needed to make ``{"domain": "adipogenesis", "task": ...}`` answerable.

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
    AdipogenesisAssessmentInput,
    AdipogenesisFlag,
    AdipogenesisIntent,
)
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
PACK_ID = "adipogenesis.minimal.v1"
ENGINE = "adipogenesis_assessment"

TASK_ASSESS = "assess_state"
TASK_MECHANISM = "explain_mechanism"

_TASK_INTENT = {
    TASK_ASSESS: AdipogenesisIntent.DIFFERENTIATION_ASSESSMENT,
    TASK_MECHANISM: AdipogenesisIntent.MECHANISM_EXPLANATION,
}


class AdipogenesisDomainPack:
    """Connects the adipogenesis vertical to the generic query boundary."""

    domain = DOMAIN
    supported_tasks: tuple[str, ...] = (TASK_ASSESS, TASK_MECHANISM)

    def execute(self, query: ReasoningQuery, store: KnowledgeStore) -> ReasoningResponse:
        data = self._to_input(query)
        if query.task == TASK_MECHANISM:
            report = build_mechanism_report(data, store)
            return self._to_response(query, report, DecisionSupport())
        outcome = assess(data, store)
        return self._to_response(query, outcome.report, self._decision_support(outcome))

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
