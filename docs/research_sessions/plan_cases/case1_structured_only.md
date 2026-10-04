# Case 1: structured-only answer, written before the revised draft was run

This is condition 2: the same host, evidence, objectives and hypotheses as
`case1_revised_draft.json`, written as predictions with references, bases and assumptions.
**No VCRP computation was run for it.** Like case 2, it is not independent: the host had
already seen the stage A analysis of the original case 1 draft.

## Corrections the host makes by hand to the original matrix

- **E1 "loss reduction by inhibitor" (present/absent) is a change.** It becomes "original
  material remaining, inhibitor vs vehicle":
  - H1 increase (less loss);
  - H2 and H3 no change.
- **E1 cannot say anything about H5.** H5 predicts less degradation *than non-activated cells*,
  and E1 has no activated/non-activated arm. The original H5 cells in E1 (decrease) were against
  the wrong reference. They become `not_predicted`, and H5's degradation claim moves to E5.
- **E1's crosslinking arm gets an H4 prediction.** Original material remaining, crosslinked vs
  not: increase. Every other hypothesis is left unpredicted there, because crosslinking may slow
  proteolysis and hydrolysis too. So the arm still separates nothing. It stays as a function
  check paired with E2 (the ingress cost).
- **E3 is read over chase time** (vs start of chase), not against a vague baseline.
- **E4 with gap length** separates H3 (contraction: gap shortens) from H6 (handover: gap kept).
  It **does not show handover**. H6 says new collagen "begins to carry load", and no readout in
  the plan measures load carried by new collagen. Continuity is carried by the bridge as a whole.
  E4 therefore reaches O3 only through a proxy. So does E3: retention is not load-bearing.

## Predictions, by hand

| exp | readout (reference) | H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 |
|---|---|---|---|---|---|---|---|---|---|
| E1 | original remaining (vs acellular) | ↓ | = | = | | ? | | | |
| E1 | original remaining (inhibitor vs vehicle) | ↑ | = | = | | | | | |
| E1 | original remaining (crosslinked vs not) | ? | ? | ? | ↑ | | | | |
| E1 | construct area (vs acellular) | = | = | ↓ | | | | | |
| E2 | nuclei at depth (crosslinked vs not) | | | | ↓ | | | | |
| E3 | new type I retained (vs chase start) | | | | | | ↑ | = | |
| E3 | new type I in medium (vs chase start) | | | | | | ? | ↑ | |
| E4 | continuity (cell-laden vs acellular) | ↓ | | ↑ | | | ↑ | = | |
| E4 | gap length (vs initial) | = | | ↓ | | | = | | |
| E5 | contraction after withdrawal (vs no TGF-β1) | | | | | ↑ | | | = |
| E5 | α-SMA after withdrawal (vs no TGF-β1) | | | | | ↑ | | | = |
| E5 | degraded collagen uptake (vs no TGF-β1) | | | | | ↓ | | | = |

**Pairs never separated, by hand:**
- H4 against everything: its only predictions are on readouts no other hypothesis predicts.
- H2 vs H3 is separated by E1 area.
- H5 vs H1 to H4, H6 and H7 is not separated: they predict nothing in E5.

**Objective coverage:**
- O1 direct (E4).
- O2 direct (E2).
- O3 proxy only (E3, E4).
- O4 proxy only (E5). In vitro, the long-term scar objective cannot be tested directly.

**If the Dupuytren passage were withdrawn** (`lit-670133a47aa6`), the E3 predictions would lose
their method basis. M4 would lose one of its two spans; they are one study.

**If the cells are not lung myofibroblasts** (M1's condition), H5's uptake prediction loses its
only mechanism support.

**First experiment:** unchanged. E3 with chase time, read together with E4 with gap length.
