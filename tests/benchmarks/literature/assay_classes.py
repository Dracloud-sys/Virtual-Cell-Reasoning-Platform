"""What counts as which kind of evidence, spelled out so the tally can be argued with.

Shared by ``build_hits.py`` (which applies these to fetched abstracts) and kept beside the
committed hit matrix so a reader can check a classification without re-fetching anything.

Each pattern names an *evidence class* — a thing an author offers in support of "we
established an immortalized line" — not a single assay. ``karyotype / cytogenetics``
covers karyotyping, CGH and ploidy statements alike, because the claim they support is the
same one.
"""

from __future__ import annotations

#: Ordered for reading, not by frequency. Matched case-insensitively against
#: title + abstract + author keywords.
PATTERNS: dict[str, str] = {
    "passages / population doublings": r"passag|population doubling|\bPDL\b|doublings",
    "growth curve / doubling time": (
        r"growth curve|doubling time|growth kinetic|proliferation rate|growth rate"
    ),
    "telomerase activity": r"telomerase activity|TRAP assay",
    "telomere length": r"telomere length|telomere extension|telomere shorten|telomere maintenance",
    "SA-beta-gal / senescence stain": r"galactosidase|SA-?.?-?gal\b|senescence[- ]associated",
    "karyotype / cytogenetics": (
        r"karyotyp|chromosome number|cytogenetic|chromosom\w* aberration|aneuploid"
        r"|near-diploid|ploidy|comparative genomic hybridi"
    ),
    "soft agar / anchorage / colony": r"soft agar|anchorage|colony form|cloning efficiency",
    "tumorigenicity in vivo": (
        r"tumorigenic|tumourigenic|nude mice|SCID|xenograft|tumou?r formation"
    ),
    "morphology": r"morpholog",
    "differentiation capacity": r"differentiat",
    "marker / phenotype expression": r"marker|phenotyp|surface antigen",
    "apoptosis": r"apoptos|apoptotic",
    "p16 / p21 / p53 / Rb pathway": r"\bp16\b|\bp21\b|\bp53\b|INK4|retinoblastoma|\bRb\b|\bpRB\b",
    "gamma-H2AX (DNA damage)": r"H2AX",
}

#: The three conditions ``agents/immortalization/baseline.py`` requires *together* before it
#: will return ``possible_candidate``. Named here so the tally reports them as a set rather
#: than leaving a reader to spot the conjunction themselves.
GATE_CLASSES: tuple[str, ...] = (
    "passages / population doublings",
    "gamma-H2AX (DNA damage)",
    "growth curve / doubling time",
)
