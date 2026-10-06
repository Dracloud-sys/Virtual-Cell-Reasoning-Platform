# Review r1: normalisation reference vs comparison group; detection vs model state

This review corrects how the r0 files of this record read the data. It does not add data,
re-run anything or change any model.

The r0 files are kept byte for byte (`../SHA256SUMS`):
- `README.md`;
- `sources.json`;
- `extracted.json`;
- `measurement_record.json`;
- `mapping_review.md`.

`check_baselines.py` reads `../extracted.json` only and writes `baselines.json`. For each
value it gives:
- the number as the authors give it, relative to PBS;
- where it lies against the same line's untreated values;
- where it lies, separately, against the DMSO value.

## 1. Normalisation reference and comparison group, per panel

| Panel | Normalisation reference (= 1) | Comparison group the question needs | Why that group | What cannot be identified |
|---|---|---|---|---|
| 6B | PBS-treated cells, one row per line | Untreated (two values) and DMSO (one value), each a separate row with its own value | Untreated is the "no inhibitor" state. DMSO is a vehicle control: the Fig 4A legend names DMSO as the vehicle for U0126 in that experiment, but neither the Fig 6B legend nor its file says so for 6B. Neither group is privileged here. | Which group the authors meant "increase" against. The values are the authors' ratios to PBS, not to untreated or DMSO. |
| 6C | One t0 sample (the file's third t0 row is 1) | The t0 samples: the legend says untreated and DMSO controls are shown at t = 0 | — | Which of the three t0 rows is untreated, DMSO or the reference sample. The file does not say, and none is assumed. |
| 6D | Untreated samples at the 0 time point (legend). Not plotted. | The no-AZD6244 samples at 30, 60 and 120 min (open symbols) | — | The t0 reference is not shown. The later no-inhibitor points are about 1.2–1.4 in HCT116 and SW480 (about 1 in RKO and HT29), as read from the figure; they are not 1 by construction. Replicate values and their spread at t0 are unknown. |

**Corrected:** "every ratio sets untreated to 1 by construction" (r0 `README.md` and
`mapping_review.md` (c); `measurement_record.json` checklist).
- **6B:** PBS is 1. Untreated is 0.79/0.86 (HCT116), 0.68/0.79 (HT29), 1.04/1.17 (RKO) and
  0.88/1.12 (SW480). DMSO is 1.11, 1.07, 1.08 and 1.01.
- **6C:** one t0 sample is 1.
- **6D:** untreated at t0 is the reference; untreated at later times is not 1.

A value such as HCT116 6.0086 at 50 µM is ×6.0 **relative to PBS**. It is not ×6.0 relative
to untreated or to DMSO, and it is not converted here. The paper's "six-fold increase" is the
authors' wording.

## 2. Low doses and the two KRAS lines, value by value

Each value is a single record, and there are one or two per dose. The table describes where
each one lies. It does not make a claim of significant change or of equivalence.

| Line, dose | Value vs PBS (line) | vs untreated values | vs DMSO value |
|---|---|---|---|
| HCT116 0.5 µM | 0.900 (7), 1.071 (8) | above both | below |
| HCT116 1 µM | 0.778 (9) | below both (0.786, 0.860) | below |
| SW480 0.5 µM | 0.717 (55) | below both (0.883, 1.117) | below |
| SW480 0.5 µM | 1.091 (56) | between them | above |
| SW480 1 µM | 0.917 (57) | between them | below |
| HCT116 5–50 µM | 2.10, 1.16 (5); 3.61; 4.92; 6.01 (lines 10–14) | above both | above |
| SW480 5–20 µM | 1.23, 2.18 (5); 1.57; 3.81 (lines 58–61) | above both | above |
| SW480 50 µM | 0.254 (62) | below both | below |
| HCT116 100 µM | 0.084 (15) | below both | below |
| SW480 100 µM | 0.020 (63) | below both | below |

**Corrected:**
- r0 P2's "within or near the control values" and `mapping_review.md`'s "within the control
  range" pooled PBS, DMSO and untreated. Neither holds value by value: several low-dose values
  are below every untreated value, or below DMSO.
- The README's "increase at 5–50 µM U0126" merged the two lines. HCT116 is above both groups
  from 5 to 50 µM; SW480 from 5 to 20 µM, and below both at 50 µM.

**Allowed reading.** At the mid doses named above, each line's values exceed every untreated
value and the DMSO value. At 0.5–1 µM, the single values fall on different sides of the
references. No direction is claimed for the low doses.

## 3. Detection, absence and the Boolean state

**Withdrawn:** this r0 branch.
> untreated near blank → "absent" → the observation is absent → present → both models put
> untreated pMek in the wrong category

It ran three different things together:
- **Analytical detection:** whether a signal can be told apart from background in this assay.
  That needs the assay's variability, its blank and control conditions, and a criterion. Raw
  readings alone do not give one. A general definition does not stand in for the validation of
  the kit actually used.
- **Biological absence:** whether the phosphorylated protein is not there at all. Signal near
  background does not show this.
- **The model's inactive state:** a Boolean value in a logical path. Mapping an assay class to
  it needs a readout mapping, plus a relation of conditions, time and population level.
  Neither classification above supplies that mapping.

**Revised branches** for the same next action (see section 5): raw readings, blanks, suitable
controls and the assay's validation information.
- **Both untreated and treated are analytically detected under a valid criterion.** Ask
  whether the change lies within one detection class. The Boolean models' inability to state
  a size remains.
- **Untreated cannot be told from background, or this is uncertain.** Detection is limited or
  undecided, and so is any mapping to a model state. Nothing is promoted to biological absence
  or to a refutation of a model.
- **The information is not obtained (the present state).** The absolute detection class stays
  unknown. The per-condition normalised observations already in hand stay as recorded.

In no branch is "both models are wrong" concluded automatically. M1's logical path and one
population measurement point stay different kinds of thing in every branch.

## 4. M2 and RKO: quantitative observations vs Boolean computations

**M2 (KRAS).**
- `active → active` is a computation that the Boolean category is the same. It is not a
  computation that a quantity stays the same.
- Declaring that an observed rise counts as a change does not turn M2 into a prediction of
  equal quantities.
- **With the assumption** "equal Boolean category = equal measured quantity": M2's no_change
  disagrees with the rise above untreated and DMSO at mid doses.
- **Without that assumption:** M2 says nothing about the size of pMek within "active", so the
  rise is outside what it computes. That is neither agreement nor disagreement.

**RKO, Fig 6B, recorded separately:**
- **Normalised values:** every U0126 value (0.39–0.63 at 0.5–10 µM; lower above) is below
  each untreated value (1.04, 1.17) and below DMSO (1.08), relative to PBS.
- **Reproduction or test:** none. There are one or two values per dose and no statistics, so
  the decrease is not confirmed as reproducible or significant.
- **What the models can express:** both give `all_active → all_active`. A Boolean model cannot
  express a decrease within "active".
- **What follows:** a disagreement holds only under the added assumption "equal Boolean
  category = equal measured quantity".

The text's "no increase in B-Raf-mutated cells" and these lower normalised values do not
contradict each other.

**Unchanged:**
- The r0 and r1 classes in `logic_biology_v1/` stand as recorded.
- The values found here do not resolve the Boolean readout's limits.

## 5. Still unknown, and the next action

**Still unknown:**
- raw Bio-Plex readings;
- blank and background handling;
- the assay's variability and detection criterion for this kit;
- linear range;
- protein normalisation;
- replicate unit;
- which 6C t0 row is untreated, DMSO or the reference;
- the vehicle U0126 was given in for 6B (DMSO is named for Fig 4A only).

**Next action (kept).** Check the raw readings, the blanks, suitable controls, and the assay's
validation information for Fig 6B or 6D. The outcomes are those of section 3. Obtaining them is
not a condition for closing this review. No authors were contacted and no experiment was
performed.
