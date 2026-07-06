"""Orchestration of cooperating agents.

v0.1 provides a minimal orchestrator that dispatches a query to one or more named
agents and merges their evidence-tagged outputs. When LangGraph is installed, the
same routing can be expressed as a graph; the ``build_graph`` hook is where that
integration lands. The default path has no hard dependency on LangGraph.
"""

from __future__ import annotations

from virtualcell.core.agent import AgentContext
from virtualcell.core.confidence import combine_confidences
from virtualcell.core.contracts import AgentInput, AgentOutput
from virtualcell.core.registry import AgentRegistry
from virtualcell.core.registry import registry as default_registry


class Orchestrator:
    """Routes a request through selected agents and aggregates their outputs."""

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        context: AgentContext | None = None,
    ) -> None:
        self.registry = registry or default_registry
        self.context = context or AgentContext()

    async def run(self, agent_name: str, inputs: AgentInput) -> AgentOutput:
        """Run a single agent by name."""
        agent = self.registry.create(agent_name, self.context)
        return await agent.run(inputs)

    async def run_many(self, agent_names: list[str], inputs: AgentInput) -> AgentOutput:
        """Run several agents and merge their claims into one aggregate output."""
        outputs = [await self.run(name, inputs) for name in agent_names]
        claims = [claim for out in outputs for claim in out.claims]
        return AgentOutput(
            agent="orchestrator",
            claims=claims,
            confidence=combine_confidences(out.confidence for out in outputs),
            notes=f"aggregated {len(outputs)} agent(s): {', '.join(agent_names)}",
        )

    def build_graph(self):  # pragma: no cover - optional LangGraph integration
        """Return a LangGraph graph for this orchestrator (requires ``langgraph``)."""
        raise NotImplementedError(
            "LangGraph integration lands in a subsequent release; "
            "install with the 'orchestration' extra."
        )
