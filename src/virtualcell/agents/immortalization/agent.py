"""ImmortalizationAssessmentAgent — intent dispatch over the three builders (PR5c-3).

The agent is a thin adapter: it routes an input to the deterministic assessment
builder, the Q5/Q6 mechanism grounding, or the Q9 hypothesis policy, and packages
the resulting `DecisionReport` onto the common `AgentOutput`. It recomputes nothing
— status, flags, claim tiers and citations come from the builders/policy unchanged.
No natural-language parsing, no LLM.
"""

from __future__ import annotations

from pydantic import ValidationError

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.grounding import build_mechanism_report
from virtualcell.agents.immortalization.hypotheses import build_hypothesis_report
from virtualcell.agents.immortalization.models import (
    ASSESSMENT_INTENTS,
    AssessmentIntent,
    ImmortalizationAssessmentInput,
)
from virtualcell.agents.immortalization.rules import UnsupportedIntentError, build_decision_report
from virtualcell.core.agent import AgentContext, BaseAgent
from virtualcell.core.confidence import mean_confidence
from virtualcell.core.contracts import AgentInput, AgentOutput
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.decision import DecisionReport


class AssessmentInputError(ValueError):
    """Raised when an `AgentInput` does not carry a valid assessment payload."""


class ImmortalizationAssessmentAgent(BaseAgent):
    name = "immortalization_assessment"
    responsibilities = "Produce deterministic, evidence-graded immortalization DecisionReports."

    def __init__(
        self, context: AgentContext | None = None, store: KnowledgeStore | None = None
    ) -> None:
        super().__init__(context)
        # Match the registry convention: a store may be injected directly (tests) or
        # supplied through the agent context's services (registry / API).
        resolved = store or self.context.services.get("knowledge_store")
        if resolved is None:
            raise ValueError(
                "ImmortalizationAssessmentAgent requires a knowledge_store "
                "(pass store=... or context.services['knowledge_store'])"
            )
        self.store = resolved

    def assess(self, data: ImmortalizationAssessmentInput) -> DecisionReport:
        """Dispatch to the right builder by intent; recompute nothing."""
        if data.intent in ASSESSMENT_INTENTS:
            return build_decision_report(data)
        if data.intent == AssessmentIntent.MECHANISM_EXPLANATION:
            return build_mechanism_report(data, self.store)
        if data.intent == AssessmentIntent.HYPOTHESIS_HANDLING:
            return build_hypothesis_report(data, self.store)
        raise UnsupportedIntentError(f"unhandled intent: {data.intent.value!r}")  # pragma: no cover

    async def run(self, inputs: AgentInput) -> AgentOutput:
        data = self._input_from_agent_input(inputs)
        report = self.assess(data)

        claims = [*report.supporting_evidence, *report.contradicting_evidence]
        confidence = mean_confidence(c.confidence for c in claims) if claims else 0.5
        return AgentOutput(
            agent=self.name,
            claims=claims,
            confidence=confidence,
            notes=report.conclusion,
            result=report.model_dump(mode="json"),
        )

    @staticmethod
    def _input_from_agent_input(inputs: AgentInput) -> ImmortalizationAssessmentInput:
        payload = inputs.context.get("assessment")
        if not isinstance(payload, dict):
            raise AssessmentInputError("AgentInput.context['assessment'] must be a dict")
        if "intent" not in payload:
            raise AssessmentInputError("assessment payload is missing 'intent'")
        scenario = {key: value for key, value in payload.items() if key != "intent"}
        try:
            return input_from_scenario(payload["intent"], scenario)
        except ValidationError as exc:
            raise AssessmentInputError(f"invalid assessment payload: {exc}") from exc
