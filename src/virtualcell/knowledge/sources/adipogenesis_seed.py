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

PPARG, CEBPA, FABP4, ADIPOQ, WNT10B, DLK1 = (
    "gene:PPARG",
    "gene:CEBPA",
    "gene:FABP4",
    "gene:ADIPOQ",
    "gene:WNT10B",
    "gene:DLK1",
)
PROGRAM, LIPOGENESIS, WNT_SIGNALLING, PREADIPO_MAINTENANCE = (
    "mechanism:adipogenic_transcription_program",
    "mechanism:lipogenesis",
    "mechanism:wnt_beta_catenin_signalling",
    "mechanism:preadipocyte_state_maintenance",
)
ADIPOCYTE, LIPID_LADEN, UNDIFFERENTIATED = (
    "phenotype:adipocyte_differentiation",
    "phenotype:lipid_accumulation",
    "phenotype:undifferentiated_preadipocyte",
)
M_PPARG, M_CEBPA, M_FABP4, M_ADIPOQ, M_LIPID = (
    "marker:PPARG_expression",
    "marker:CEBPA_expression",
    "marker:FABP4_expression",
    "marker:ADIPOQ_expression",
    "marker:lipid_content",
)
A_OILRED, A_QPCR, A_TRIGLYCERIDE = (
    "assay:oil_red_o",
    "assay:adipogenic_qpcr_panel",
    "assay:triglyceride_quantification",
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
]
_PHENOTYPES: list[tuple[str, str]] = [
    (ADIPOCYTE, "Adipocyte differentiation"),
    (LIPID_LADEN, "Lipid accumulation"),
    (UNDIFFERENTIATED, "Undifferentiated preadipocyte"),
]
_MARKERS: list[tuple[str, str, str]] = [
    (M_PPARG, "PPARG expression", "molecular"),
    (M_CEBPA, "CEBPA expression", "molecular"),
    (M_FABP4, "FABP4 expression", "molecular"),
    (M_ADIPOQ, "ADIPOQ expression", "molecular"),
    (M_LIPID, "Lipid content", "functional"),
]
_ASSAYS: list[tuple[str, str, str]] = [
    (A_OILRED, "Oil Red O staining", "lipid_stain"),
    (A_QPCR, "Adipogenic qPCR panel", "expression"),
    (A_TRIGLYCERIDE, "Triglyceride quantification", "biochemical"),
]

# (source, relation, target, confidence, provenance)
_EDGES: list[tuple[str, RelationType, str, float, list[str]]] = [
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
    # Active restraint. "Not differentiating" and "being held back" are different findings.
    (WNT10B, RelationType.PROMOTES, WNT_SIGNALLING, 0.9, _CURATED),
    (WNT_SIGNALLING, RelationType.INHIBITS, PROGRAM, 0.85, _CURATED),
    (DLK1, RelationType.PROMOTES, PREADIPO_MAINTENANCE, 0.85, _CURATED),
    (PREADIPO_MAINTENANCE, RelationType.INHIBITS, PROGRAM, 0.8, _CURATED),
    (PREADIPO_MAINTENANCE, RelationType.PROMOTES, UNDIFFERENTIATED, 0.85, _CURATED),
    # Assays report; they never drive.
    (A_QPCR, RelationType.INDICATES, PROGRAM, 0.8, _CURATED),
    (A_OILRED, RelationType.INDICATES, LIPID_LADEN, 0.85, _CURATED),
    (A_TRIGLYCERIDE, RelationType.INDICATES, LIPID_LADEN, 0.85, _CURATED),
    # What to run when a call cannot be made.
    (ADIPOCYTE, RelationType.SUGGESTS_NEXT_TEST, A_OILRED, 0.7, _CURATED),
    (ADIPOCYTE, RelationType.SUGGESTS_NEXT_TEST, A_QPCR, 0.7, _CURATED),
    (UNDIFFERENTIATED, RelationType.SUGGESTS_NEXT_TEST, A_TRIGLYCERIDE, 0.6, _CURATED),
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
