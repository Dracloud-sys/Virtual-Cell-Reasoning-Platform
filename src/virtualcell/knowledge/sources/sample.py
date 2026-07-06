"""A small, self-contained sample dataset.

This connector requires no network access and exists so the knowledge base,
example script, and Literature Agent are demonstrable out of the box. The biology
is a simplified, illustrative slice (TP53 / MDM2 / apoptosis) and is not a curated
reference.
"""

from __future__ import annotations

from collections.abc import Iterator

from virtualcell.knowledge.schema import (
    Gene,
    Interaction,
    Pathway,
    Protein,
    RelationType,
)


class SampleDataSource:
    """A tiny curated example graph around the p53 pathway."""

    name = "sample"

    def entities(self) -> Iterator:
        yield Gene(
            id="gene:TP53",
            name="TP53",
            symbol="TP53",
            organism="Homo sapiens",
            aliases=["p53", "tumor protein p53"],
            description="Tumor suppressor gene; guardian of the genome.",
        )
        yield Protein(
            id="protein:P04637",
            name="Cellular tumor antigen p53",
            uniprot_id="P04637",
            aliases=["p53", "TP53"],
            description="Transcription factor mediating cell-cycle arrest and apoptosis.",
        )
        yield Gene(
            id="gene:MDM2",
            name="MDM2",
            symbol="MDM2",
            organism="Homo sapiens",
            aliases=["HDM2"],
            description="Negative regulator of p53.",
        )
        yield Protein(
            id="protein:Q00987",
            name="E3 ubiquitin-protein ligase Mdm2",
            uniprot_id="Q00987",
            aliases=["MDM2", "HDM2"],
            description="Ubiquitinates p53, targeting it for degradation.",
        )
        yield Pathway(
            id="pathway:apoptosis",
            name="Apoptosis",
            source="Reactome",
            aliases=["programmed cell death"],
            description="Regulated cell-death program.",
        )

    def interactions(self) -> Iterator[Interaction]:
        yield Interaction(
            source_id="gene:TP53",
            target_id="protein:P04637",
            relation=RelationType.ENCODES,
            evidence=["curated:sample"],
        )
        yield Interaction(
            source_id="gene:MDM2",
            target_id="protein:Q00987",
            relation=RelationType.ENCODES,
            evidence=["curated:sample"],
        )
        yield Interaction(
            source_id="protein:Q00987",
            target_id="protein:P04637",
            relation=RelationType.REGULATES,
            confidence=0.95,
            evidence=["curated:sample"],
        )
        yield Interaction(
            source_id="protein:P04637",
            target_id="pathway:apoptosis",
            relation=RelationType.PARTICIPATES_IN,
            confidence=0.9,
            evidence=["curated:sample"],
        )
