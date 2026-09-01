"""Curated genome-editing seed graph — the third vertical's substrate.

Domain in one line: a nuclease makes a double-strand break, the cell repairs it, and *which
repair pathway ran* decides what you ended up with. NHEJ gives indels and, with luck, a
frameshift; HDR gives a templated knock-in. Everything the assessment judges is downstream of
that fork.

Deliberately disjoint from both existing graphs — no shared node, no shared edge. A third
domain that entangled with the first would be a weaker generality test, not a stronger one.

Evidence discipline, following the immortalization and adipogenesis seeds:

* ``PROMOTES`` / ``INHIBITS`` encode biological direction, independent of evidence tier.
* A ``marker:`` node carries the ``INDICATES`` edge, never an ``assay:`` node — an assay is
  what you run, a marker is what it reads, and only a reading can indicate a phenotype (the
  PR16 ontology rule).
* **The domain's headline rule is encoded in the relation vocabulary.** ``marker:allele_sequence``
  *indicates* a repair outcome; ``marker:amplicon_size`` is only ``ASSOCIATED_WITH`` one. A
  band and a genotype are different strengths of evidence, and the graph says so rather than
  leaving the assessment to assert it alone.
* Nothing here claims that an edit makes a protein disappear or a genome clean. Both are
  separate claims with separate evidence, and the pack's safety policy forbids asserting them.

*** Curated draft for platform-generality work; not a reviewed biological reference. ***
"""

from __future__ import annotations

from collections.abc import Iterator

from virtualcell.knowledge.schema import (
    AssayResult,
    BioEntity,
    Gene,
    Interaction,
    Marker,
    Mechanism,
    Phenotype,
    RelationType,
)

_CURATED = ["curated:genome_editing_seed"]
_WEAK_BAND = [
    "curated:genome_editing_seed",
    "An amplicon size shift is consistent with an integration but does not read the allele.",
]

CAS9, TP53 = "gene:CAS9", "gene:TP53"

DSB, NHEJ, HDR, FRAMESHIFT, KNOCK_IN, DDR = (
    "mechanism:double_strand_break",
    "mechanism:nhej_repair",
    "mechanism:hdr_repair",
    "mechanism:frameshift",
    "mechanism:knock_in_integration",
    "mechanism:dna_damage_response",
)

LOSS_OF_FUNCTION, CASSETTE, MOSAIC, OFF_TARGET = (
    "phenotype:loss_of_function",
    "phenotype:cassette_integration",
    "phenotype:mosaic_population",
    "phenotype:off_target_edit",
)

ALLELE, AMPLICON, PROTEIN, OFF_TARGET_SITES = (
    "marker:allele_sequence",
    "marker:amplicon_size",
    "marker:protein_level",
    "marker:off_target_sites",
)

PCR_SCREEN, SANGER, NGS, OFF_TARGET_SCREEN, WESTERN = (
    "assay:pcr_screen",
    "assay:sanger_sequencing",
    "assay:targeted_ngs",
    "assay:off_target_screen",
    "assay:western_blot",
)

_GENES = [
    (
        CAS9,
        "SpCas9",
        "RNA-guided nuclease; introduces a targeted double-strand break.",
        ["Cas9", "CRISPR nuclease"],
    ),
    (
        TP53,
        "TP53",
        "Tumor suppressor p53; mounts the damage response a double-strand break provokes.",
        ["p53"],
    ),
]

_MECHANISMS = [
    (DSB, "Targeted double-strand break", "The event every downstream outcome descends from."),
    (
        NHEJ,
        "Non-homologous end joining",
        "Error-prone religation; the usual source of small indels.",
    ),
    (HDR, "Homology-directed repair", "Template-dependent repair; the route to a knock-in."),
    (
        FRAMESHIFT,
        "Frameshift indel",
        "An indel that is not a multiple of three and disrupts the reading frame.",
    ),
    (KNOCK_IN, "Templated cassette integration", ""),
    (DDR, "DNA damage response", ""),
]

_PHENOTYPES = [
    (LOSS_OF_FUNCTION, "Loss of gene function"),
    (CASSETTE, "Cassette present at the target locus"),
    (MOSAIC, "Mosaic edited population (risk)"),
    (OFF_TARGET, "Unintended edit elsewhere in the genome (risk)"),
]

_MARKERS = [
    (ALLELE, "Allele sequence at the target locus", "sequence"),
    (AMPLICON, "Amplicon size at the target locus", "electrophoretic"),
    (PROTEIN, "Target protein level", "molecular"),
    (OFF_TARGET_SITES, "Sequence at candidate off-target sites", "sequence"),
]

_ASSAYS = [
    (PCR_SCREEN, "PCR screen across the target locus", "pcr"),
    (SANGER, "Sanger sequencing of the target amplicon", "sequencing"),
    (NGS, "Targeted amplicon NGS", "sequencing"),
    (OFF_TARGET_SCREEN, "Off-target screen", "sequencing"),
    (WESTERN, "Western blot for the target protein", "immunoblot"),
]

_R = RelationType
_EDGES: list[tuple[str, RelationType, str, float, list[str]]] = [
    # The break, and the fork that decides what you get.
    (CAS9, _R.PROMOTES, DSB, 0.95, _CURATED),
    (DSB, _R.PROMOTES, NHEJ, 0.9, _CURATED),
    (DSB, _R.PROMOTES, HDR, 0.75, _CURATED),
    (DSB, _R.PROMOTES, DDR, 0.85, _CURATED),
    (TP53, _R.PROMOTES, DDR, 0.9, _CURATED),
    # A damage response that is running restrains the repair route that needs a template.
    (DDR, _R.INHIBITS, HDR, 0.6, _CURATED),
    # NHEJ arm -> indel -> loss of function.
    (NHEJ, _R.PROMOTES, FRAMESHIFT, 0.8, _CURATED),
    (FRAMESHIFT, _R.PROMOTES, LOSS_OF_FUNCTION, 0.8, _CURATED),
    # HDR arm -> integration -> cassette present.
    (HDR, _R.PROMOTES, KNOCK_IN, 0.85, _CURATED),
    (KNOCK_IN, _R.PROMOTES, CASSETTE, 0.9, _CURATED),
    # Editing an unsynchronised population is how mosaicism arises.
    (NHEJ, _R.ASSOCIATED_WITH, MOSAIC, 0.6, _CURATED),
    (CAS9, _R.ASSOCIATED_WITH, OFF_TARGET, 0.55, _CURATED),
    # Readouts. The strength difference between a sequence and a band is the domain's
    # headline rule, so it is carried by the relation rather than asserted in prose.
    (ALLELE, _R.INDICATES, FRAMESHIFT, 0.9, _CURATED),
    (ALLELE, _R.INDICATES, KNOCK_IN, 0.9, _CURATED),
    (AMPLICON, _R.ASSOCIATED_WITH, KNOCK_IN, 0.5, _WEAK_BAND),
    (PROTEIN, _R.INDICATES, LOSS_OF_FUNCTION, 0.85, _CURATED),
    (OFF_TARGET_SITES, _R.INDICATES, OFF_TARGET, 0.85, _CURATED),
    # What to run next, hung on the risk that motivates it.
    (LOSS_OF_FUNCTION, _R.SUGGESTS_NEXT_TEST, WESTERN, 0.8, _CURATED),
    (CASSETTE, _R.SUGGESTS_NEXT_TEST, SANGER, 0.8, _CURATED),
    (MOSAIC, _R.SUGGESTS_NEXT_TEST, NGS, 0.8, _CURATED),
    (OFF_TARGET, _R.SUGGESTS_NEXT_TEST, OFF_TARGET_SCREEN, 0.8, _CURATED),
    (KNOCK_IN, _R.SUGGESTS_NEXT_TEST, PCR_SCREEN, 0.6, _CURATED),
]


class GenomeEditingSeedSource:
    """Bundled curated genome-editing graph (no external file)."""

    name = "genome_editing_seed"

    def entities(self) -> Iterator[BioEntity]:
        for gene_id, name, description, aliases in _GENES:
            yield Gene(id=gene_id, name=name, description=description, aliases=aliases, symbol=name)
        for mechanism_id, name, description in _MECHANISMS:
            yield Mechanism(id=mechanism_id, name=name, description=description or None)
        for phenotype_id, name in _PHENOTYPES:
            yield Phenotype(id=phenotype_id, name=name)
        for marker_id, name, modality in _MARKERS:
            yield Marker(id=marker_id, name=name, modality=modality)
        for assay_id, name, assay in _ASSAYS:
            yield AssayResult(id=assay_id, name=name, assay=assay)

    def interactions(self) -> Iterator[Interaction]:
        for source_id, relation, target_id, confidence, evidence in _EDGES:
            yield Interaction(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                confidence=confidence,
                evidence=list(evidence),
            )
