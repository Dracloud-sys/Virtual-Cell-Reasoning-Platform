"""Core abstractions shared across all Virtual Cell modules.

Modules depend only on the protocols and models defined here, never on each
other directly. This keeps every module independently replaceable.
"""

from __future__ import annotations

from virtualcell.core.agent import AgentContext, BaseAgent, MemoryStore
from virtualcell.core.confidence import combine_confidences
from virtualcell.core.contracts import AgentInput, AgentOutput, Message
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.core.registry import AgentRegistry, registry

__all__ = [
    "AgentContext",
    "AgentInput",
    "AgentOutput",
    "AgentRegistry",
    "BaseAgent",
    "Claim",
    "EvidenceTier",
    "MemoryStore",
    "Message",
    "combine_confidences",
    "registry",
]
