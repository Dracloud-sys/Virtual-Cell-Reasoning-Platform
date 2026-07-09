"""Curated immortalization seed graph (cell-engineering vertical, v0).

A small, hand-curated graph encoding the immortalization decision domain over the
v0 ontology, so `explain` produces the mechanistic chains the benchmark
(``tests/benchmarks/immortalization_v0.md``) requires. It is bundled (no file
needed) and merges cleanly onto the molecular substrate.

Evidence discipline (do not weaken):
* Established mechanistic edges use ``PROMOTES`` / ``INHIBITS`` with high
  confidence.
* The reported spontaneous route (Believer Meats, Nature Food 2025) is
  **P53-independent** and is seeded only as ``ASSOCIATED_WITH`` / ``SUGGESTS``
  with low confidence — never ``CAUSES``, never "P53 loss / without P53".

Signs (promote vs inhibit) are carried on the edge label, not composed by
`explain`; the agent / LLM interprets them.

*** This content is a DRAFT for domain-expert (biologist) review. ***
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

_CURATED = ["curated:immortalization_seed"]
_SPONTANEOUS = ["hypothesis; Believer Meats, Nature Food 2025 (P53-independent)"]

# Node ids (single source of truth, referenced by both node lists and edges).
TERT, CDK4, CDKN2A, RB1, TP53, CDKN1A, PPARGC1A = (
    "gene:TERT", "gene:CDK4", "gene:CDKN2A", "gene:RB1", "gene:TP53",
    "gene:CDKN1A", "gene:PPARGC1A",
)
TELO, REPSEN, P16, G1S, DDR, MITO, SPON = (
    "mechanism:telomere_maintenance", "mechanism:replicative_senescence",
    "mechanism:p16_rb_arrest", "mechanism:g1s_progression",
    "mechanism:dna_damage_response", "mechanism:mitochondrial_function",
    "mechanism:spontaneous_immortalization",
)
SUST, SEN, GENOM, LOSSDIFF = (
    "phenotype:sustained_proliferation", "phenotype:senescence",
    "phenotype:genomic_instability", "phenotype:loss_of_differentiation",
)
PDL, DT, H2AX, SABGAL = "marker:PDL", "marker:DT", "marker:gammaH2AX", "marker:SA_b_gal"
KARYO, DIFF = "assay:karyotype", "assay:differentiation"

# --- nodes: (id, name, description) ---------------------------------------

_GENES = [
    (TERT, "TERT", "Telomerase reverse transcriptase (catalytic subunit)."),
    (CDK4, "CDK4", "Cyclin-dependent kinase 4; drives G1/S with cyclin D."),
    (CDKN2A, "CDKN2A", "p16INK4a; CDK4/6 inhibitor enforcing the p16-RB checkpoint."),
    (RB1, "RB1", "Retinoblastoma protein; restrains G1/S until phosphorylated."),
    (TP53, "TP53", "Tumor suppressor p53; DNA-damage response and arrest."),
    (CDKN1A, "CDKN1A", "p21; p53-induced CDK inhibitor causing cell-cycle arrest."),
    (PPARGC1A, "PPARGC1A", "PGC-1alpha; master regulator of mitochondrial biogenesis."),
]
_MECHANISMS = [
    (TELO, "Telomere maintenance"),
    (REPSEN, "Replicative (telomeric) senescence"),
    (P16, "p16-RB checkpoint arrest (G1/S)"),
    (G1S, "G1/S cell-cycle progression"),
    (DDR, "DNA damage response"),
    (MITO, "Mitochondrial function"),
    (SPON, "Spontaneous immortalization (P53-independent)"),
]
_PHENOTYPES = [
    (SUST, "Sustained proliferation (immortalization candidate)"),
    (SEN, "Senescence (growth arrest)"),
    (GENOM, "Genomic instability (risk)"),
    (LOSSDIFF, "Loss of differentiation (risk)"),
]
_MARKERS = [
    (PDL, "PDL (population doubling level)", "functional"),
    (DT, "DT (doubling time)", "functional"),
    (H2AX, "gammaH2AX", "molecular"),
    (SABGAL, "SA-beta-Gal", "molecular"),
]
_ASSAYS = [
    (KARYO, "Karyotype / genomic-stability assay"),
    (DIFF, "Differentiation assay (adipogenic / myogenic)"),
]

# --- edges: (source, relation, target, confidence, evidence) --------------

_R = RelationType
_EDGES: list[tuple[str, RelationType, str, float, list[str]]] = [
    # TERT arm: telomere maintenance delays replicative senescence.
    (TERT, _R.PROMOTES, TELO, 0.95, _CURATED),
    (TELO, _R.INHIBITS, REPSEN, 0.9, _CURATED),
    (REPSEN, _R.INHIBITS, SUST, 0.9, _CURATED),
    (REPSEN, _R.PROMOTES, SEN, 0.9, _CURATED),
    # p16-RB checkpoint arm.
    (CDKN2A, _R.PROMOTES, P16, 0.95, _CURATED),
    (RB1, _R.PROMOTES, P16, 0.85, _CURATED),
    (P16, _R.INHIBITS, G1S, 0.9, _CURATED),
    (P16, _R.PROMOTES, SEN, 0.85, _CURATED),
    # CDK4 bypasses p16-mediated arrest and drives G1/S (the key TERT+CDK4 insight).
    (CDK4, _R.INHIBITS, P16, 0.9, _CURATED),
    (CDK4, _R.PROMOTES, G1S, 0.9, _CURATED),
    (G1S, _R.PROMOTES, SUST, 0.9, _CURATED),
    # p53 / p21 / DNA damage arm.
    (TP53, _R.PROMOTES, DDR, 0.9, _CURATED),
    (TP53, _R.REGULATES, CDKN1A, 0.9, _CURATED),
    (CDKN1A, _R.INHIBITS, G1S, 0.85, _CURATED),
    # PGC1A / mitochondria (established), then the weak spontaneous route.
    (PPARGC1A, _R.PROMOTES, MITO, 0.85, _CURATED),
    (TERT, _R.ASSOCIATED_WITH, SPON, 0.55, _SPONTANEOUS),
    (PPARGC1A, _R.ASSOCIATED_WITH, SPON, 0.55, _SPONTANEOUS),
    (SPON, _R.SUGGESTS, SUST, 0.5, _SPONTANEOUS),
    # Marker readouts indicate mechanisms / phenotypes.
    (PDL, _R.INDICATES, SUST, 0.8, _CURATED),
    (DT, _R.INDICATES, SEN, 0.7, _CURATED),
    (H2AX, _R.INDICATES, DDR, 0.85, _CURATED),
    (H2AX, _R.INDICATES, SEN, 0.75, _CURATED),
    (SABGAL, _R.INDICATES, SEN, 0.85, _CURATED),
    # Caveats: immortalization != safety / function — what to check next.
    (SUST, _R.SUGGESTS_NEXT_TEST, KARYO, 0.8, _CURATED),
    (SUST, _R.SUGGESTS_NEXT_TEST, DIFF, 0.8, _CURATED),
    (LOSSDIFF, _R.CONTRADICTS, DIFF, 0.7, _CURATED),
]


class ImmortalizationSeedSource:
    """Bundled curated seed graph for immortalization reasoning (v0 draft)."""

    name = "immortalization_seed"

    def entities(self) -> Iterator[BioEntity]:
        src = {"source": self.name}
        for eid, name, desc in _GENES:
            yield Gene(id=eid, name=name, symbol=name, description=desc, properties=src)
        for eid, name in _MECHANISMS:
            yield Mechanism(id=eid, name=name, properties=src)
        for eid, name in _PHENOTYPES:
            yield Phenotype(id=eid, name=name, properties=src)
        for eid, name, modality in _MARKERS:
            yield Marker(id=eid, name=name, modality=modality, properties=src)
        for eid, name in _ASSAYS:
            yield AssayResult(id=eid, name=name, properties=src)

    def interactions(self) -> Iterator[Interaction]:
        for source_id, relation, target_id, confidence, evidence in _EDGES:
            yield Interaction(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                confidence=confidence,
                evidence=evidence,
            )
