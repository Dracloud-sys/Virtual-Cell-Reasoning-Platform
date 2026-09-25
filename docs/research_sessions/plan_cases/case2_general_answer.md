# Case 2 — general answer (written before the plan analysis was run)

Same host, same evidence as the plan case (`lit-*` ids from the product-path reads recorded in
`case2_draft.json`). No `plan_analysis` was consulted while writing this.

**Question (not a registered domain).** A compound lowers the resazurin (alamarBlue) signal of a
fibroblast culture. Is that fewer cells, less reducing/metabolic activity per cell, or the
compound interfering with the assay? The researcher wants to know which before calling the
compound cytotoxic. Cell type and compound class are not fixed.

**Candidate explanations (can co-occur).** H1 fewer cells (death or arrest). H2 lower reductive
capacity per cell (metabolic/mitochondrial). H3 assay interference by the compound.

**Evidence.** Resazurin and MTT signals reflect reductive/metabolic activity, not cell number per
se (lit-86b42ebcd0c4, lit-126b0584c71b); interference by coloured/fluorescent/redox-active
substances is a recognised source of misclassification and apparent cytotoxicity should be
confirmed orthogonally (lit-86b42ebcd0c4, lit-c400e3eff71e). Metabolic readings can move without
viability changing, e.g. with serum removal (lit-479e219aad4e). Mitochondrial mass can fall while
respiration per mitochondrion is preserved (lit-5559327e689b, lit-d4f08afd7961).

**Plan.**

1. Cell-free control: resazurin + compound, no cells — detects interference.
2. Count cells / DNA at the same time point and express resazurin per cell — separates H1 from H2.
3. Orthogonal endpoint: membrane integrity (live/dead) and ATP.
4. If H2: OCR (Seahorse) normalised to cell number and to mitochondrial content (citrate synthase),
   noting the maximal-OCR caveat (lit-be2c3c428bde).

**Which first.** 1 and 2 together in one plate: cheap, and they rule interference in or out and
split H1 from H2.
