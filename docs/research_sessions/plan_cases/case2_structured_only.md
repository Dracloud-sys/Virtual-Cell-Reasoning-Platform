# Case 2: structured-only answer, written before the revised draft was run

This is the second of the three conditions. It uses the same host, the same evidence and the
same hypotheses as `case2_revised_draft.json`, and it is written in the same structured form:
predictions per readout, with basis and assumptions. But **no VCRP computation was run** for
it. Pairs, traces and dependencies were worked out by hand.

**It is not independent.** The host writing it had already seen the stage A analysis of the
original draft and had just written `case2_matrix_review.md`. It measures what writing the
structure buys without the computation, from a writer who already knows what the computation
flagged last time. A fresh writer would likely do worse, not better.

## Plan

| exp | readout (reference) | H1 | H2a | H2b | H3a | H3b |
|---|---|---|---|---|---|---|
| E1 | fluorescence (vs resazurin alone) | = | = | = | ? | ? |
| E2 | resorufin fluorescence (vs resorufin alone) | = | = | = | ? | ↓ |
| E3 | DNA cell number (vs vehicle) | ↓ | = | = | =ᵃ | =ᵃ |
| E3 | resazurin per cell (vs vehicle) | = | ↓ | ↓ | ↓ | ↓ |
| E4 | membrane-compromised fraction (vs vehicle) | ? | = | = | =ᵃ | =ᵃ |
| E4 | ATP per cell (vs vehicle) | =ᵃ | ? | ? | =ᵃ | =ᵃ |
| E5 | citrate synthase per cell (vs vehicle) | = | ↓ | = | =ᵃ | =ᵃ |
| E5 | OCR per citrate synthase (vs vehicle) | = | = | ? | =ᵃ | =ᵃ |

ᵃ Holds only if the compound does not interfere with that assay. That is an assumption, not a
control in the plan.

**Pairs, by hand.**
- H1 vs everything else: E3 cell number.
- H2a vs H2b: E5 citrate synthase.
- H3b vs H1, H2a, H2b: E2.
- H3b vs H2a: also E5 citrate synthase, under an assumption.
- H3b vs H2b: no general-answer readout differs.
- H3a: only E1 and E2 could show it, and neither fixes a direction for it.
- H3a vs H3b: nothing separates them.

**Evidence behind the H3b row.**
- The graphene product-control passage (`lit-fd67cab1bedc`) and the cell-free limitation
  (`lit-d1719f786da7`) are one study. Count it once.
- The other H3b-relevant span, `lit-c400e3eff71e`, is from the OECD review. It is general, not
  about resorufin.

**If the graphene evidence were withdrawn.**
- H3b's E2 prediction would lose its only observed basis and become an assumption from the
  measurement model.
- M1 goes with it.

**First experiment.** One plate: E1 + E2 + E3, with an ATP + compound cell-free check, if ATP is
going to be used as the orthogonal endpoint.

## What this answer did not produce

- It did not enumerate the pairs it did not compare.
- It did not list the readouts whose specification is incomplete.
- It did not list every prediction that shares an assumption.

It could have, by hand. It did not do so here.
