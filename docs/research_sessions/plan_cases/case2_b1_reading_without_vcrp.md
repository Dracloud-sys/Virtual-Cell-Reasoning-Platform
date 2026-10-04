# Case 2 B1: the synthetic results read without VCRP

These are conditions 1 and 2 for the observation step. The host wrote both after
`case2_b1_observations.json` existed and **before** `compare_research_observations` was run on
it. The rules in `case2_b1_rules.json` (committed in d7d8bc2) were known when this was written.
The general answer is how the host would read the numbers without the rule file.

All numbers are synthetic.

## Condition 1: a competent general reading

- **S1.** Resorufin + compound reads about half of resorufin alone, and cell counts are flat.
  So the compound quenches or adsorbs the product. The per-cell drop in resazurin is what
  quenching alone would produce. Do not call it cytotoxic, and do not use resazurin for this
  compound. Check biology with a non-resorufin endpoint.
- **S2.** No product interference. Cells are not fewer, but per-cell signal is down about 40%.
  ATP is unchanged, and the luciferase standard is unaffected by the compound. The fall is
  metabolic but not energetic: reductase activity per cell dropped while ATP held, perhaps by
  glycolysis. Next: content and OCR (E5).
- **S3.** The product control is inconsistent: one replicate is unaffected, two are down.
  Per-cell signal is down about 15%. Repeat before concluding anything.
- **S4.** E2 looks like strong quenching (0.55). Per-cell signal is down about half. ATP is
  down. Citrate synthase is down about 40%. Together that reads as interference plus less
  mitochondrial content.

## Condition 2: structured by hand, against the committed rules

| scenario | readout | by hand | H1 | H2a | H2b | H3a | H3b |
|---|---|---|---|---|---|---|---|
| S1 | E2 resorufin | ↓ | ✗ | ✗ | ✗ | – | ✓ |
| S1 | E3 cell number | = | ✗ | ✓ | ✓ | ✓ᵃ | ✓ᵃ |
| S1 | E3 per cell | ↓ | ✗ | ✓ | ✓ | ✓ | ✓ |
| S2 | E2 resorufin | = | ✓ | ✓ | ✓ | – | ✗ |
| S2 | E3 cell number | = | ✗ | ✓ | ✓ | ✓ᵃ | ✓ᵃ |
| S2 | E3 per cell | ↓ | ✗ | ✓ | ✓ | ✓ | ✓ |
| S2 | E4 ATP | = | ✓ᵃ | – | – | ✓ᵃ | ✓ᵃ |
| S2 | E6 luciferase | = (assumption holds) | | | | | |
| S3 | E2 resorufin | replicates split | ? | ? | ? | ? | ? |
| S3 | E3 per cell | 0.85: between bands | ? | ? | ? | ? | ? |
| S4 | all | see below | | | | | |

ᵃ Holds only under the assumption that the assay is not affected by the compound. – means no
value was predicted.

**S4 by hand, with the rule file open.**
- E2 is in AU while the rule assumes RFU.
- The E3 vehicle arm is at 48 h and the compound arm at 24 h.
- Every compound ATP reading is suspect or a bound.
- The E5 run says "absorbance", while the readout spec says "DTNB absorbance". The host would
  probably have accepted that as the same assay.

None of these four is comparable.

**Where condition 1 went wrong.** It read S4 as if every value were usable:
- a unit mismatch;
- a 24 h vs 48 h comparison;
- ATP readings that were suspect, or were bounds;

and it produced a biological story from them. The structured reading caught S4 only because
the rule file was open.

**What neither reading enumerated.**
- Each S1 "✗" for H2a and H2b on E2 means only that H2 alone does not predict a cell-free
  decrease. That does not count against H2, which can coexist with H3b.
- Which predictions share the assumption about the DNA dye.
