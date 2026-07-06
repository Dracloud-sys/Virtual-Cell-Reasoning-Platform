"""Shared base for the v0.1 stub agents.

A stub agent declares its identity and returns a single, honest ``speculative``
placeholder claim so the orchestration flow is exercisable end to end before the
real reasoning is implemented.
"""

from __future__ import annotations

from virtualcell.core.agent import BaseAgent
from virtualcell.core.contracts import AgentInput, AgentOutput
from virtualcell.core.evidence import Claim, EvidenceTier


class StubAgent(BaseAgent):
    """Base class for not-yet-implemented agents."""

    name = "stub"
    responsibilities = "placeholder"

    async def run(self, inputs: AgentInput) -> AgentOutput:
        claim = Claim(
            statement=(f"[{self.name}] not yet implemented; received query: {inputs.query!r}"),
            tier=EvidenceTier.SPECULATIVE,
            confidence=0.0,
            assumptions=["agent is a v0.1 stub"],
        )
        return AgentOutput(
            agent=self.name,
            claims=[claim],
            confidence=0.0,
            notes="stub implementation",
        )
