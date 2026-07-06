"""Validation Agent.

Cross-cutting agent that checks other agents' outputs for evidence-tier hygiene:
every claim must carry a tier, and speculative claims should declare assumptions.
This is a lightweight, working check in v0.1 (not a stub).
"""

from __future__ import annotations

from virtualcell.core.agent import BaseAgent
from virtualcell.core.contracts import AgentInput, AgentOutput
from virtualcell.core.evidence import Claim, EvidenceTier


class ValidationAgent(BaseAgent):
    name = "validation"
    responsibilities = "Verify evidence-tier hygiene and internal consistency of claims."

    async def run(self, inputs: AgentInput) -> AgentOutput:
        # The claims to validate are passed via context["claims"] as dicts.
        raw_claims = inputs.context.get("claims", [])
        problems: list[str] = []
        for i, raw in enumerate(raw_claims):
            claim = raw if isinstance(raw, Claim) else Claim.model_validate(raw)
            if claim.tier == EvidenceTier.SPECULATIVE and not claim.assumptions:
                problems.append(f"claim {i}: speculative claim without stated assumptions")
            if claim.tier == EvidenceTier.ESTABLISHED and not claim.citations:
                problems.append(f"claim {i}: established claim without citations")

        ok = not problems
        summary = "all claims pass evidence-tier checks" if ok else "; ".join(problems)
        return AgentOutput(
            agent=self.name,
            claims=[
                Claim(
                    statement=summary,
                    tier=EvidenceTier.ESTABLISHED,
                    confidence=1.0 if ok else 0.5,
                    citations=["internal:evidence-policy"],
                )
            ],
            confidence=1.0 if ok else 0.5,
            notes="validation report",
        )
