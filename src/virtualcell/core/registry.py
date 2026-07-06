"""Agent registry for discovery by the orchestrator.

Agents register a factory under their name; the orchestrator instantiates them on
demand with a shared context.
"""

from __future__ import annotations

from collections.abc import Callable

from virtualcell.core.agent import AgentContext, BaseAgent

AgentFactory = Callable[[AgentContext], BaseAgent]


class AgentRegistry:
    """A simple name -> factory registry."""

    def __init__(self) -> None:
        self._factories: dict[str, AgentFactory] = {}

    def register(self, name: str, factory: AgentFactory) -> None:
        if name in self._factories:
            raise ValueError(f"agent already registered: {name}")
        self._factories[name] = factory

    def create(self, name: str, context: AgentContext | None = None) -> BaseAgent:
        if name not in self._factories:
            raise KeyError(f"no agent registered under: {name}")
        return self._factories[name](context or AgentContext())

    def names(self) -> list[str]:
        return sorted(self._factories)

    def __contains__(self, name: object) -> bool:
        return name in self._factories


registry = AgentRegistry()
"""Process-wide default registry."""
