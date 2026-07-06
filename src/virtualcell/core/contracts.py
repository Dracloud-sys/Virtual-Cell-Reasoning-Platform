"""Pydantic data contracts for inter-agent communication.

Agents exchange these typed structures rather than raw dicts, so that message
shapes are validated and self-documenting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from virtualcell.core.evidence import Claim


class Message(BaseModel):
    """A message routed between agents by the orchestrator."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    sender: str
    recipient: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentInput(BaseModel):
    """Standard input envelope for :meth:`BaseAgent.run`."""

    query: str
    context: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    """Standard output envelope returned by every agent.

    Results are expressed as evidence-tagged :class:`Claim` objects so that
    downstream consumers always know the epistemic status of each statement.
    """

    agent: str
    claims: list[Claim] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: str | None = None
