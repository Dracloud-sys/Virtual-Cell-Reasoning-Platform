"""Biological entity and relationship schema for the knowledge base.

These are deliberately minimal for v0.1 and cover the entities needed to
demonstrate graph and semantic queries. They respect the biological hierarchy
(genome -> transcriptome -> proteome -> pathways).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    # Molecular substrate (horizontal graph)
    GENE = "gene"
    PROTEIN = "protein"
    PATHWAY = "pathway"
    # Cell-engineering vertical ontology (v0)
    CELL_LINE = "cell_line"
    MARKER = "marker"
    ASSAY_RESULT = "assay_result"
    PHENOTYPE = "phenotype"
    MECHANISM = "mechanism"


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


# --- Cell-engineering vertical ontology (v0) ---


class CellLine(BioEntity):
    type: EntityType = EntityType.CELL_LINE
    species: str | None = None
    cell_type: str | None = None  # e.g. "fibroblast", "preadipocyte"


class Marker(BioEntity):
    type: EntityType = EntityType.MARKER
    modality: str | None = None  # "molecular" | "functional"


class AssayResult(BioEntity):
    type: EntityType = EntityType.ASSAY_RESULT
    assay: str | None = None
    value: str | None = None
    unit: str | None = None
    direction: str | None = None  # e.g. "up" | "down" | "high" | "low" | "worsening"
    timepoint: str | None = None


class Phenotype(BioEntity):
    type: EntityType = EntityType.PHENOTYPE


class Mechanism(BioEntity):
    type: EntityType = EntityType.MECHANISM


class RelationType(StrEnum):
    # Molecular substrate
    ENCODES = "encodes"  # gene -> protein
    INTERACTS_WITH = "interacts_with"  # protein <-> protein
    PARTICIPATES_IN = "participates_in"  # protein -> pathway
    REGULATES = "regulates"  # gene/protein -> gene/protein
    # Cell-engineering vertical (v0)
    HAS_RESULT = "has_result"  # cell line -> assay result
    INDICATES = "indicates"  # assay result / marker -> phenotype / mechanism
    SUPPORTS = "supports"  # evidence -> conclusion
    CONTRADICTS = "contradicts"  # evidence -> conclusion
    ASSOCIATED_WITH = "associated_with"  # weak, non-causal linkage
    SUGGESTS = "suggests"  # weak directional hint (never CAUSES)
    SUGGESTS_NEXT_TEST = "suggests_next_test"  # gap / phenotype -> assay to run


# Relations whose biological meaning is symmetric (A relates to B iff B relates to A).
# For every other relation the edge is directed: a reverse edge is stored only as a
# traversal convenience and must not be followed as a forward (causal) step.
SYMMETRIC_RELATIONS: frozenset[RelationType] = frozenset(
    {RelationType.INTERACTS_WITH, RelationType.ASSOCIATED_WITH}
)


class Interaction(BaseModel):
    """A typed, directed edge between two entities."""

    source_id: str
    target_id: str
    relation: RelationType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
