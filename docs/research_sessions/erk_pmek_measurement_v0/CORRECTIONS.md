# Corrections to this record

The r0 files are kept byte for byte as committed at `1f5b41c` (`SHA256SUMS`):
- `README.md`;
- `sources.json`;
- `extract.py`;
- `extracted.json`;
- `measurement_record.json`;
- `mapping_review.md`.

This file lists where they are corrected or narrowed. The reasoning and the value-by-value
table are in `review_r1/README.md` and `review_r1/baselines.json`.

## Normalisation reference vs comparison group

- **"Untreated is 1 by construction".** This appears in `README.md` (units and next action), in
  `mapping_review.md` K1 (c), and in the `measurement_record.json` checklist ("signal unit and
  axis"). It is wrong for 6B: PBS is 1, while untreated and DMSO are separate rows with their
  own values. In 6C one t0 sample is 1, and which row is untreated or DMSO cannot be
  identified. In 6D untreated at t0 is the reference, and untreated at later times is not 1.
- **"Controls 0.79–1.11", "against controls 0.68–1.07" and similar.** These appear in
  `measurement_record.json` P1, P4 and P5. They pooled PBS, DMSO and untreated into one range.
  The values are now placed against untreated and DMSO separately.
- **"×6.0" and "×3.8".** In `README.md` and `mapping_review.md`, these are relative to PBS,
  not to untreated or DMSO.

## Low doses and the two KRAS lines

- **P2: "within or near the control values" at 0.5–1 µM**, and `mapping_review.md`'s "within
  the control range". This does not hold value by value:
  - SW480 at 0.5 µM, 0.717, is below both untreated values and DMSO;
  - HCT116 at 1 µM, 0.778, is below both untreated values;
  - HCT116 at 0.5 µM is above both untreated values but below DMSO.

  No direction is claimed for the low doses.
- **"5–50 µM increase"** in `README.md` and `mapping_review.md` K1 (summary) merged the two
  lines:
  - HCT116 is above untreated and DMSO from 5 to 50 µM;
  - SW480 from 5 to 20 µM, and below both at 50 µM (0.254).

## Detection, absence and model state

- **The branch "untreated near blank → absent → both models put untreated in the wrong
  category" is withdrawn.** It appears in `README.md` (next action) and in the PR description.
  Signal near background is not by itself non-detection under a valid criterion. Nor is it
  biological absence, or a Boolean 0. Mapping any of them to a model state needs a readout
  mapping and its conditions. The revised branches are in `review_r1/README.md` section 3.

## M2 and RKO

- **M2's `active → active`** is the same Boolean category, not an unchanged quantity. Its
  disagreement with the observed rise holds only under the assumption "equal Boolean category
  = equal measured quantity". Without it, the rise is outside what M2 computes.
- **RKO in 6B.** Its values are below each untreated value and DMSO, relative to PBS. This is
  one or two values per dose with no test, so it is neither reproduced nor tested. A Boolean
  model cannot express a decrease within "active". It disagrees only under the same added
  assumption. The text's "no increase" does not contradict these values.

## Unchanged

- The r0 and r1 classes in `logic_biology_v1/`.
- The models, the inputs and the extracted values.
- The next action: raw readings, blanks, suitable controls and assay validation information.
  Only its outcome branches are revised.
