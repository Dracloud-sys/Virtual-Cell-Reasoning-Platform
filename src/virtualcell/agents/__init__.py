"""Specialized agents.

Importing this package registers all built-in agents with the default registry.
Literature, Literature Discovery, Validation and Immortalization Assessment are
functional; Genome, Transcription, Protein Interaction, Metabolism and Signaling
are interface stubs (see ``base_stub.py``).

This registry is **not** the domain-pack registry. The adipogenesis and
genome-editing verticals live under ``virtualcell.agents.<domain>`` but are
reached through ``virtualcell.platform`` rather than being registered here, so
they do not appear in ``virtualcell agents``. See ``docs/agents.md``.
"""

from __future__ import annotations

from virtualcell.agents.genome.agent import GenomeAgent
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.agents.literature.agent import LiteratureAgent
from virtualcell.agents.literature_discovery.agent import LiteratureDiscoveryAgent
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
registry.register("literature_discovery", LiteratureDiscoveryAgent)
registry.register("validation", ValidationAgent)
registry.register("immortalization_assessment", ImmortalizationAssessmentAgent)

__all__ = [
    "GenomeAgent",
    "ImmortalizationAssessmentAgent",
    "LiteratureAgent",
    "LiteratureDiscoveryAgent",
    "MetabolismAgent",
    "ProteinInteractionAgent",
    "SignalingAgent",
    "TranscriptionAgent",
    "ValidationAgent",
]
