"""Specialized agents.

Importing this package registers all built-in agents with the default registry.
In v0.1 every agent except :class:`LiteratureAgent` is a stub.
"""

from __future__ import annotations

from virtualcell.agents.genome.agent import GenomeAgent
from virtualcell.agents.literature.agent import LiteratureAgent
from virtualcell.agents.metabolism.agent import MetabolismAgent
from virtualcell.agents.protein_interaction.agent import ProteinInteractionAgent
from virtualcell.agents.signaling.agent import SignalingAgent
from virtualcell.agents.transcription.agent import TranscriptionAgent
from virtualcell.agents.validation.agent import ValidationAgent
from virtualcell.core.registry import registry

registry.register("genome", GenomeAgent)
registry.register("transcription", TranscriptionAgent)
registry.register("protein_interaction", ProteinInteractionAgent)
registry.register("metabolism", MetabolismAgent)
registry.register("signaling", SignalingAgent)
registry.register("literature", LiteratureAgent)
registry.register("validation", ValidationAgent)

__all__ = [
    "GenomeAgent",
    "LiteratureAgent",
    "MetabolismAgent",
    "ProteinInteractionAgent",
    "SignalingAgent",
    "TranscriptionAgent",
    "ValidationAgent",
]
