"""Immortalization domain pack — the first reference vertical (PR11).

A thin adapter, and deliberately nothing more. It maps a generic
:class:`~virtualcell.platform.contracts.ReasoningQuery` onto the *actual product path*
(``ImmortalizationAssessmentAgent.assess``, the same entry point the API, CLI and
benchmark use) and converts the resulting ``DecisionReport`` into the generic envelope.

It contains **no** scientific rules: no thresholds, no status derivation, no claim
construction, no tier decisions. Everything scientific comes from the agent and the
policies behind it (``rules`` / ``grounding`` / ``hypotheses``), unchanged. The
conversion is lossless — the full report is preserved verbatim in ``domain_details`` —
so PR10's claim boundaries, evidence tiers, citations, and the Q5/Q6/Q9 corrections
survive the boundary intact.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.contracts import (
    DecisionSupport,
    ExplanationLevel,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.domains import QueryValidationError
from virtualcell.reasoning.decision import DecisionReport

DOMAIN = "immortalization"
PACK_ID = "immortalization.reference.v1"
ENGINE = "immortalization_assessment"

# Platform task -> the vertical's own intent vocabulary. ``assess_state`` covers the four
# assessment intents and takes the specific one from the normalised experiment payload
# (preserving the PR10 input shape); the mechanism and hypothesis tasks are fixed because
# they name a single intent each.
TASK_ASSESS = "assess_state"
TASK_MECHANISM = "explain_mechanism"
TASK_HYPOTHESIS = "handle_hypothesis"

_FIXED_INTENT = {
    TASK_MECHANISM: "mechanism_explanation",
    TASK_HYPOTHESIS: "hypothesis_handling",
}
_DEFAULT_ASSESS_INTENT = "immortalization_assessment"
# The flag that means "a single snapshot is not enough here" — surfaced on the envelope
# because it is a decision the caller must act on.
_TREND_FLAG = "trend_needed"


class ImmortalizationDomainPack:
    """Connects the immortalization vertical to the generic query boundary."""

    domain = DOMAIN
    supported_tasks: tuple[str, ...] = (TASK_ASSESS, TASK_MECHANISM, TASK_HYPOTHESIS)

    def execute(self, query: ReasoningQuery, store: KnowledgeStore) -> ReasoningResponse:
        data = self._to_assessment_input(query)
        report = ImmortalizationAssessmentAgent(store=store).assess(data)
        return self._to_response(query, report)

    # --- request adaptation --------------------------------------------------

    def _to_assessment_input(self, query: ReasoningQuery):
        experiment = dict(query.experiment)
        intent = _FIXED_INTENT.get(query.task) or experiment.pop("intent", _DEFAULT_ASSESS_INTENT)
        # A fixed-intent task must not be contradicted by a stray payload intent.
        experiment.pop("intent", None)
        try:
            return input_from_scenario(intent, experiment)
        except (ValidationError, ValueError) as exc:
            raise QueryValidationError(
                f"invalid immortalization experiment payload: {exc}"
            ) from exc

    # --- response conversion (normalise; never reinterpret) ------------------

    def _to_response(self, query: ReasoningQuery, report: DecisionReport) -> ReasoningResponse:
        flags = [f.value for f in report.flags]
        return ReasoningResponse(
            domain=self.domain,
            task=query.task,
            summary=report.conclusion,
            observations=self._observations(report),
            # Input conflicts and withheld overrides are acquisition/QC findings, not
            # biological conclusions, so they are reported as such.
            quality_findings=[*report.input_conflicts, *report.blocked_overrides],
            interpretations=list(report.conflict_explanation),
            # Immortalization expresses hypotheses as HYPOTHESIS-tier claims inside its
            # evidence rather than as free-standing statements, so this stays empty
            # instead of being filled with a restatement.
            hypotheses=[],
            supporting_evidence=[c.model_copy(deep=True) for c in report.supporting_evidence],
            contradicting_evidence=[c.model_copy(deep=True) for c in report.contradicting_evidence],
            mechanistic_links=[link.model_copy(deep=True) for link in report.mechanistic_chain],
            missing_information=list(report.missing_axes),
            uncertainties=list(report.uncertainty),
            limitations=list(report.limitations),
            overinterpretation_risks=list(report.overinterpretation_risk),
            decision_support=DecisionSupport(
                status=report.candidate_status.value if report.candidate_status else None,
                flags=flags,
                trend_required=_TREND_FLAG in flags,
            ),
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
            # Verbatim, so normalisation can never lose or reshape the domain report.
            domain_details={"decision_report": report.model_dump(mode="json")},
        )

    @staticmethod
    def _observations(report: DecisionReport) -> list[str]:
        """The marker values the assessment actually consumed.

        ``derived_input`` records where a raw series replaced a snapshot label, so this
        reports what was observed without restating any interpretation of it.
        """
        observations = [f"{axis}={value}" for axis, value in sorted(report.derived_input.items())]
        trajectory: dict[str, Any] | None = report.trajectory
        if trajectory and trajectory.get("state"):
            observations.append(f"trajectory={trajectory['state']}")
        return observations


def explanation_levels() -> list[str]:
    """The validated explanation levels (exposed for CLI/API help text)."""
    return [level.value for level in ExplanationLevel]
