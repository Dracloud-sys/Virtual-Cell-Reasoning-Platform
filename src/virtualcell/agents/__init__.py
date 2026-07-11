"""Specialized agents.

Importing this package registers all built-in agents with the default registry.
The Literature and Immortalization Assessment agents are functional; the other
specialized domain agents are interface stubs.
"""

from __future__ import annotations

from virtualcell.agents.genome.agent import GenomeAgent
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
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
registry.register("immortalization_assessment", ImmortalizationAssessmentAgent)

__all__ = [
    "GenomeAgent",
    "ImmortalizationAssessmentAgent",
    "LiteratureAgent",
    "MetabolismAgent",
    "ProteinInteractionAgent",
    "SignalingAgent",
    "TranscriptionAgent",
    "ValidationAgent",
]
