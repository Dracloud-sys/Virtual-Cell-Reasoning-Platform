# Model–observation link v0, review r2

This review closes two gaps left after review r1 (`ab92e77`):
- a group of cases with no model value was dropped, and the remaining groups were compared as
  if they were the whole model;
- a declared category that happened to be called `indeterminate` was read as the rule's
  between-bands class.

The earlier records are not changed:
- `../` (v0) and `../review_r1/` still match their `SHA256SUMS`;
- their cases rebuild unchanged.

`cases.py` here builds every new input from the v0 and review r1 builders. Every call goes to
`compare_model_observation` (or `run_logic_model`) on `build_server()`.

## Reproduced before the fix (`ab92e77`, product path)

| Input | Before | After |
|---|---|---|
| T3, unedited | `partial`, undecided | unchanged |
| **B1:** T3, every case still in its group; the `no_change` group's directions `[]`; `paired.directions` = union of the rest | **`single_match`, consistent**: case 1 was dropped | refused: `paired.groups[1].directions is empty for cases [1]` |
| **B2:** T3, every case still in its group; all directions `[]` | **`outside`, inconsistent**: no prediction read as a mismatch | refused: `paired.groups[0].directions is empty for cases [0]` |
| **I1:** C1 with A renamed `indeterminate` in vocabulary, table and readings | **`between_bands`, undecided** (C1: consistent) | `single_match`, consistent |
| **I2:** C2, same rename | **`between_bands`, undecided** (C2: inconsistent) | `outside`, inconsistent |
| **I3:** C3, same rename | **`between_bands`**, undecided (C3: `partial`) | `partial`, undecided |

Which stage let these through:
- **B1 and B2:** the review r1 checks passed them. Each case was in exactly one group, and the
  top-level directions equalled the union.
- **B1 and B2, claim:** `_model_claim` turned an empty group into a group with no values,
  without marking anything not computed.
- **B1 and B2, relation:** `_relate` compared only the values it found. The remaining groups gave
  `{increase}` for B1 and nothing for B2, which it read as not containing the observed class.
- **I1–I3:** no input validation stopped them. The link, vocabulary and table were well formed.
  `_relate` returned `between_bands` for any observed string equal to `indeterminate`, before
  looking at what kind of observation it was.

## What changed

**Groups without values:**
- **Refused:** a paired group that names cases but carries no direction, with the field and the
  cases named.
  - The window is never empty, so the engine gives every case a direction for every step.
  - When a value is not computed, that direction is `undetermined`, never nothing.
- **Accepted:** a real engine result whose directions are `undetermined` (U1: `norule`, Z has no
  rule) is accepted as before.
  - It is reported `insufficient` with `model_values_not_computed`, and the observation is kept.
- **Defense in depth:**
  - `_model_claim` marks the claim not computed if any group, or the claim as a whole, has no
    value, so no group is silently left out;
  - `_relate` refuses to relate a claim in which any group has no translated value. "No
    prediction" is never returned as `outside` or `inconsistent`.
- No new result grade was added.

**Category names:**
- `_relate` reads `indeterminate` as between the rule's bands only when the observation is not a
  declared category. That holds when the link has no `observed_vocabulary`, so the observed class
  came from the `DecisionRule` or from detection.
- A declared category is compared only through the table, whatever it is called.
- Category names are not changed, and `indeterminate` is not forbidden.
- Renaming a category everywhere it appears changes no outcome (I1–I3 against C1–C3).
- The numeric between-bands result is unchanged:
  - **N1:** ratio 1.3, between no_change (0.9–1.1) and increase (≥ 1.5), gives `between_bands`,
    undecided.
  - **N2, N3:** `if_accepted` uses the same reading as the comparison. N2 (reference held,
    host-proposed) gives `if_accepted` undecided. N3 (the same reference stated by the
    researcher) gives result undecided.

## Not done

- No signature, ledger, model re-run or regeneration of earlier records.
- The checks use only relations within this input.
- Valid `not_paired`, `no_baseline`, incomplete and not-computed results are accepted as before.
  The earlier tests check this.
