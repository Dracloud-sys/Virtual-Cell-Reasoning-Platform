"""Biological entity and relationship schema for the knowledge base.

These are deliberately minimal for v0.1 and cover the entities needed to
demonstrate graph and semantic queries. They respect the biological hierarchy
(genome -> transcriptome -> proteome -> pathways).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    GENE = "gene"
    PROTEIN = "protein"
    PATHWAY = "pathway"


class BioEntity(BaseModel):
    """Base class for a node in the knowledge graph."""

    id: str
    name: str
    type: EntityType
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    properties: dict[str, str] = Field(default_factory=dict)

    def text(self) -> str:
        """Concatenated text used for lightweight semantic search."""
        parts = [self.name, *self.aliases]
        if self.description:
            parts.append(self.description)
        return " ".join(parts)


class Gene(BioEntity):
    type: EntityType = EntityType.GENE
    symbol: str | None = None
    organism: str | None = None


class Protein(BioEntity):
    type: EntityType = EntityType.PROTEIN
    uniprot_id: str | None = None


class Pathway(BioEntity):
    type: EntityType = EntityType.PATHWAY
    source: str | None = None  # e.g. "Reactome", "KEGG"


class RelationType(StrEnum):
    ENCODES = "encodes"  # gene -> protein
    INTERACTS_WITH = "interacts_with"  # protein <-> protein
    PARTICIPATES_IN = "participates_in"  # protein -> pathway
    REGULATES = "regulates"  # gene/protein -> gene/protein


class Interaction(BaseModel):
    """A typed, directed edge between two entities."""

    source_id: str
    target_id: str
    relation: RelationType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
