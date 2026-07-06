"""The BaseAgent contract implemented by every specialized agent.

An agent has responsibilities, typed inputs/outputs, optional injected memory, a
reasoning process (``run``), and confidence estimation. Memory is a protocol so
backends can be swapped without changing agents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from virtualcell.core.confidence import mean_confidence
from virtualcell.core.contracts import AgentInput, AgentOutput


@runtime_checkable
class MemoryStore(Protocol):
    """Minimal key-value memory an agent may be given. Implementations vary."""

    def remember(self, key: str, value: Any) -> None: ...

    def recall(self, key: str) -> Any | None: ...


@dataclass
class InMemoryMemory:
    """Default in-process memory store."""

    _data: dict[str, Any] = field(default_factory=dict)

    def remember(self, key: str, value: Any) -> None:
        self._data[key] = value

    def recall(self, key: str) -> Any | None:
        return self._data.get(key)


@dataclass
class AgentContext:
    """Runtime context injected into an agent (dependencies, not business logic)."""

    memory: MemoryStore = field(default_factory=InMemoryMemory)
    services: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Base class for all cooperating agents.

    Subclasses set :attr:`name` and :attr:`responsibilities` and implement
    :meth:`run`. Confidence defaults to the mean of the returned claims'
    confidences but may be overridden.
    """

    name: str = "base"
    responsibilities: str = ""

    def __init__(self, context: AgentContext | None = None) -> None:
        self.context = context or AgentContext()

    @abstractmethod
    async def run(self, inputs: AgentInput) -> AgentOutput:
        """Execute the agent's reasoning process and return typed output."""
        raise NotImplementedError

    def estimate_confidence(self, output: AgentOutput) -> float:
        """Estimate overall confidence for an output (default: mean of claims)."""
        return mean_confidence(c.confidence for c in output.claims)
