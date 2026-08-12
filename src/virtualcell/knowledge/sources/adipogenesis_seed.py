"""Curated adipogenesis seed graph — the second vertical's substrate (minimal).

Deliberately small. Its job is to let the adipogenesis pack build a *real*
:class:`~virtualcell.reasoning.decision.DecisionReport`, so the immortalization and
adipogenesis report builders can be compared and PR14b can extract what is genuinely
shared. It is not a complete model of adipocyte differentiation and does not pretend to be.

Domain in one line: a preadipocyte becomes an adipocyte when the PPARG/CEBPA transcriptional
program runs and the cell actually accumulates lipid. Both halves matter, and the second is
the one that is easy to lose — a marker panel says the program is running, not that a fat
cell exists.

Evidence discipline (the same rules the immortalization seed follows):

* ``PROMOTES`` / ``INHIBITS`` encode biological *direction*, independent of evidence tier.
* WNT/beta-catenin signalling **inhibits** adipogenesis, and DLK1/PREF-1 inhibits it too;
  both are seeded as real inhibitory edges rather than as absent-positive silence, because
  "the program did not run" and "something was actively blocking it" are different findings.
* Marker assays ``INDICATES`` the program or the phenotype — never ``PROMOTES`` it. An assay
  reports on biology; it does not drive it.
* Nothing here asserts that differentiation makes a cell food, safe, or mature. Those are
  separate claims with separate evidence, and the pack's safety policy forbids asserting
  them.

Context: bovine preadipocyte differentiation is what a cultured-fat programme measures
alongside immortalization, so this is a genuinely adjacent domain rather than an invented
one — which is what makes it a fair test of the kernel boundary.

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

_CURATED = ["curated:adipogenesis_seed"]

# --- node ids (single source of truth for nodes and edges) -------------------

PPARG, CEBPA, FABP4, ADIPOQ, PLIN1, WNT10B, DLK1, CTNNB1 = (
    "gene:PPARG",
    "gene:CEBPA",
    "gene:FABP4",
    "gene:ADIPOQ",
    "gene:PLIN1",
    "gene:WNT10B",
    "gene:DLK1",
    "gene:CTNNB1",
)
PROGRAM, LIPOGENESIS, WNT_SIGNALLING, PREADIPO_MAINTENANCE = (
    "mechanism:adipogenic_transcription_program",
    "mechanism:lipogenesis",
    "mechanism:wnt_beta_catenin_signalling",
    "mechanism:preadipocyte_state_maintenance",
)
COMMITMENT, MATURATION, DROPLET_ASSEMBLY = (
    "mechanism:adipogenic_commitment",
    "mechanism:adipocyte_maturation",
    "mechanism:lipid_droplet_assembly",
)
ADIPOCYTE, LIPID_LADEN, UNDIFFERENTIATED, MATURE_ADIPOCYTE = (
    "phenotype:adipocyte_differentiation",
    "phenotype:lipid_accumulation",
    "phenotype:undifferentiated_preadipocyte",
    "phenotype:mature_adipocyte_function",
)
M_PPARG, M_CEBPA, M_FABP4, M_ADIPOQ, M_PLIN1, M_LIPID, M_EFFICIENCY, M_VIABILITY, M_MORPH = (
    "marker:PPARG_expression",
    "marker:CEBPA_expression",
    "marker:FABP4_expression",
    "marker:ADIPOQ_expression",
    "marker:PLIN1_expression",
    "marker:lipid_content",
    "marker:differentiated_fraction",
    "marker:viability",
    "marker:adipocyte_morphology",
)
A_OILRED, A_QPCR, A_TRIGLYCERIDE, A_NILE_RED, A_VIABILITY, A_IMAGING = (
    "assay:oil_red_o",
    "assay:adipogenic_qpcr_panel",
    "assay:triglyceride_quantification",
    "assay:nile_red_bodipy",
    "assay:viability",
    "assay:morphology_imaging",
)

_GENES: list[tuple[str, str, str, list[str]]] = [
    (PPARG, "PPARG", "PPAR-gamma; master transcriptional regulator of adipogenesis.", ["PPARg"]),
    (
        CEBPA,
        "CEBPA",
        "C/EBP-alpha; cooperates with PPARG to drive terminal differentiation.",
        ["CEBPalpha"],
    ),
    (FABP4, "FABP4", "Fatty-acid binding protein 4; late adipocyte marker.", ["aP2"]),
    (
        PLIN1,
        "PLIN1",
        "Perilipin-1; coats the mature lipid droplet and marks a completed program.",
        ["perilipin"],
    ),
    (
        CTNNB1,
        "CTNNB1",
        "Beta-catenin; the effector through which WNT restrains adipogenic commitment.",
        ["beta-catenin"],
    ),
    (ADIPOQ, "ADIPOQ", "Adiponectin; secreted by mature adipocytes.", ["adiponectin"]),
    (WNT10B, "WNT10B", "WNT ligand that maintains the preadipocyte state.", []),
    (
        DLK1,
        "DLK1",
        "Delta-like 1 / PREF-1; preadipocyte factor restraining differentiation.",
        ["PREF-1"],
    ),
]
_MECHANISMS: list[tuple[str, str, str]] = [
    (PROGRAM, "Adipogenic transcription program", "PPARG/CEBPA-driven differentiation program."),
    (LIPOGENESIS, "Lipogenesis", "Triglyceride synthesis and lipid-droplet accumulation."),
    (WNT_SIGNALLING, "WNT/beta-catenin signalling", "Restrains adipogenic commitment."),
    (PREADIPO_MAINTENANCE, "Preadipocyte state maintenance", "Keeps the cell undifferentiated."),
    (COMMITMENT, "Adipogenic commitment", "The decision to enter the adipocyte lineage."),
    (
        MATURATION,
        "Adipocyte maturation",
        "Acquisition of adipocyte function; downstream of, and not the same as, differentiation.",
    ),
    (DROPLET_ASSEMBLY, "Lipid droplet assembly", "Formation and coating of the lipid droplet."),
]
_PHENOTYPES: list[tuple[str, str]] = [
    (ADIPOCYTE, "Adipocyte differentiation"),
    (LIPID_LADEN, "Lipid accumulation"),
    (UNDIFFERENTIATED, "Undifferentiated preadipocyte"),
    (MATURE_ADIPOCYTE, "Mature adipocyte function"),
]
_MARKERS: list[tuple[str, str, str]] = [
    (M_PPARG, "PPARG expression", "molecular"),
    (M_CEBPA, "CEBPA expression", "molecular"),
    (M_FABP4, "FABP4 expression", "molecular"),
    (M_ADIPOQ, "ADIPOQ expression", "molecular"),
    (M_PLIN1, "PLIN1 expression", "molecular"),
    (M_LIPID, "Lipid content", "functional"),
    (M_EFFICIENCY, "Differentiated fraction", "functional"),
    (M_VIABILITY, "Viability", "functional"),
    (M_MORPH, "Adipocyte morphology", "morphological"),
]
_ASSAYS: list[tuple[str, str, str]] = [
    (A_OILRED, "Oil Red O staining", "lipid_stain"),
    (A_QPCR, "Adipogenic qPCR panel", "expression"),
    (A_TRIGLYCERIDE, "Triglyceride quantification", "biochemical"),
    (A_NILE_RED, "Nile Red / BODIPY imaging", "lipid_stain"),
    (A_VIABILITY, "Viability assay", "viability"),
    (A_IMAGING, "Morphology imaging", "imaging"),
]

# (source, relation, target, confidence, provenance)
_EDGES: list[tuple[str, RelationType, str, float, list[str]]] = [
    # Commitment precedes the program: the decision to enter the lineage is a separate
    # event from running the transcriptional course, and only the first is what an
    # inhibitor blocks.
    (PPARG, RelationType.PROMOTES, COMMITMENT, 0.9, _CURATED),
    (CEBPA, RelationType.PROMOTES, COMMITMENT, 0.85, _CURATED),
    (COMMITMENT, RelationType.PROMOTES, PROGRAM, 0.9, _CURATED),
    # The transcriptional program, and what drives it.
    (PPARG, RelationType.PROMOTES, PROGRAM, 0.95, _CURATED),
    (CEBPA, RelationType.PROMOTES, PROGRAM, 0.9, _CURATED),
    (PPARG, RelationType.PROMOTES, CEBPA, 0.8, _CURATED),
    (CEBPA, RelationType.PROMOTES, PPARG, 0.8, _CURATED),
    # Program -> function -> phenotype. Two steps on purpose: the program running is not
    # the same event as the cell filling with lipid.
    (PROGRAM, RelationType.PROMOTES, LIPOGENESIS, 0.85, _CURATED),
    (LIPOGENESIS, RelationType.PROMOTES, LIPID_LADEN, 0.9, _CURATED),
    (PROGRAM, RelationType.PROMOTES, ADIPOCYTE, 0.85, _CURATED),
    (LIPID_LADEN, RelationType.PROMOTES, ADIPOCYTE, 0.8, _CURATED),
    # Late markers are downstream of the program, not drivers of it.
    (PROGRAM, RelationType.PROMOTES, FABP4, 0.8, _CURATED),
    (PROGRAM, RelationType.PROMOTES, ADIPOQ, 0.75, _CURATED),
    (PROGRAM, RelationType.PROMOTES, PLIN1, 0.75, _CURATED),
    # Droplet assembly and maturation. Maturation is deliberately *downstream* of
    # differentiation and reached only through it: the graph must not let a lipid reading
    # short-circuit into a maturity claim, because that is the overclaim this vertical
    # exists to refuse.
    (PLIN1, RelationType.PROMOTES, DROPLET_ASSEMBLY, 0.85, _CURATED),
    (LIPOGENESIS, RelationType.PROMOTES, DROPLET_ASSEMBLY, 0.8, _CURATED),
    (ADIPOCYTE, RelationType.PROMOTES, MATURATION, 0.7, _CURATED),
    (ADIPOQ, RelationType.PROMOTES, MATURATION, 0.7, _CURATED),
    (MATURATION, RelationType.PROMOTES, MATURE_ADIPOCYTE, 0.8, _CURATED),
    # Active restraint. "Not differentiating" and "being held back" are different findings.
    (WNT10B, RelationType.PROMOTES, WNT_SIGNALLING, 0.9, _CURATED),
    (CTNNB1, RelationType.PROMOTES, WNT_SIGNALLING, 0.85, _CURATED),
    (WNT_SIGNALLING, RelationType.INHIBITS, COMMITMENT, 0.85, _CURATED),
    (WNT_SIGNALLING, RelationType.INHIBITS, PROGRAM, 0.85, _CURATED),
    (DLK1, RelationType.PROMOTES, PREADIPO_MAINTENANCE, 0.85, _CURATED),
    (PREADIPO_MAINTENANCE, RelationType.INHIBITS, COMMITMENT, 0.8, _CURATED),
    (PREADIPO_MAINTENANCE, RelationType.INHIBITS, PROGRAM, 0.8, _CURATED),
    (PREADIPO_MAINTENANCE, RelationType.PROMOTES, UNDIFFERENTIATED, 0.85, _CURATED),
    # Assays report; they never drive.
    (A_QPCR, RelationType.INDICATES, PROGRAM, 0.8, _CURATED),
    (A_OILRED, RelationType.INDICATES, LIPID_LADEN, 0.85, _CURATED),
    (A_TRIGLYCERIDE, RelationType.INDICATES, LIPID_LADEN, 0.85, _CURATED),
    (A_NILE_RED, RelationType.INDICATES, LIPID_LADEN, 0.8, _CURATED),
    (A_IMAGING, RelationType.INDICATES, ADIPOCYTE, 0.6, _CURATED),
    (A_VIABILITY, RelationType.INDICATES, UNDIFFERENTIATED, 0.5, _CURATED),
    # What to run when a call cannot be made.
    (ADIPOCYTE, RelationType.SUGGESTS_NEXT_TEST, A_OILRED, 0.7, _CURATED),
    (ADIPOCYTE, RelationType.SUGGESTS_NEXT_TEST, A_QPCR, 0.7, _CURATED),
    (UNDIFFERENTIATED, RelationType.SUGGESTS_NEXT_TEST, A_TRIGLYCERIDE, 0.6, _CURATED),
    (MATURE_ADIPOCYTE, RelationType.SUGGESTS_NEXT_TEST, A_NILE_RED, 0.6, _CURATED),
    (UNDIFFERENTIATED, RelationType.SUGGESTS_NEXT_TEST, A_VIABILITY, 0.6, _CURATED),
    (ADIPOCYTE, RelationType.SUGGESTS_NEXT_TEST, A_IMAGING, 0.5, _CURATED),
]


class AdipogenesisSeedSource:
    """Bundled curated adipogenesis graph (no external file)."""

    name = "adipogenesis_seed"

    def entities(self) -> Iterator[BioEntity]:
        for gene_id, name, description, aliases in _GENES:
            yield Gene(id=gene_id, name=name, description=description, aliases=aliases, symbol=name)
        for mechanism_id, name, description in _MECHANISMS:
            yield Mechanism(id=mechanism_id, name=name, description=description)
        for phenotype_id, name in _PHENOTYPES:
            yield Phenotype(id=phenotype_id, name=name)
        for marker_id, name, modality in _MARKERS:
            yield Marker(id=marker_id, name=name, modality=modality)
        for assay_id, name, assay in _ASSAYS:
            yield AssayResult(id=assay_id, name=name, assay=assay)

    def interactions(self) -> Iterator[Interaction]:
        for source_id, relation, target_id, confidence, provenance in _EDGES:
            yield Interaction(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                confidence=confidence,
                provenance=list(provenance),
            )
