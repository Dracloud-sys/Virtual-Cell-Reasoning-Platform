# Review r2 of `run_logic_model` (base `915eb4f`): repetition, and the baseline side

The review items came from isolated function checks. They were taken as claims to reproduce,
not as findings. `repro.py` runs each one on the product path (`run_logic_model` on
`build_server()`):
- `repro_915eb4f.json` is the result before the fix;
- `repro_after_fix.json` is the result after it.

The evidence id in R3 (`synthetic-contract-test-ev1`) is a synthetic contract-test label, not a
literature source.

## Reproduced at `915eb4f`

| | Input | At `915eb4f` | Defect |
|---|---|---|---|
| R1 | internal P, initial true, no rule, 3 steps | P `not_computed` from t1 (correct), but `repetition`: `fixed_point` from step 1 | equal not-computed states were compared and reported as a Boolean fixed point |
| R2 | U true at t0–10, false from t11; `P(next) = U`; P true; 3 steps | `constant_from: 0`, `fixed_point` from 0 | `_constant_from` dropped change points beyond the last step, so the declared change at 11 was ignored |
| R2 | same, 13 steps | `constant_from: 11`, `fixed_point` from 12 | none; correct |
| R3 | rule R `P(next) = U` with an assumption and a synthetic evidence id; baseline unclamped, scenario clamps P false; identity readout; hypothesis id | readout `decrease`; draft says "from rules [] stated by ['nobody']", with no evidence id and no rule assumption | drafts drew only on the scenario's dependencies; the scenario clamped P and used no rule, while the baseline's value came from R |

## What changed (`src/virtualcell/simulation/logic.py`)

**Repetition.** Only repetition and tracing changed; the computed state paths did not.
- **Fully computed states only.** A repeat is looked for only among states with every
  component computed. A repeat of states containing not-computed values is `not_assessed`, with
  a reason. Summaries of the components that were computed are unchanged.
- **Changes beyond the run count.** `constant_from` now keeps change points declared after the
  last step. If it is past the last step, repetition is `not_assessed` with the index named, and
  the computed path is kept. Nothing is extended or dropped.
- **Bounded `unknown_each_step` still works.** It becomes constant after its end, as before.

**Relative predictions.**
- `dependencies` still trace the scenario's own values.
- New `baseline_dependencies` trace the baseline's values the same way.
- New `relative_dependencies` give, per readout, both sides' computed-from lists apart, and the
  rules once each, with the side(s) that used them.
- A draft against a baseline names both sides' rules, and carries the evidence ids and
  assumptions of every rule either side used.
- Without a baseline, nothing changes: both new fields are empty and the draft text is the same.
- None of this is a cause, an only cause or a minimal cause. Rules stay `validated: false`, and
  drafts stay basis `assumption`.

## The reference case after the fix (`compare_case.py`, `case_compare.json`)

`../results.json` (recorded at `1660785`) is not rewritten. Re-run on the fixed code:

**Unchanged in every run:**
- the state paths, final states, repetition, scenario dependencies, differences and readouts;
- the drafts' expected values.

All 24 hand checks still match.

**Changed, tracing only:** the drafts' computed-from text in all eight comparisons now names
both sides. In four comparisons (`s3_S_off` and `s5c_S_off_from_0_P_unknown`, for A and B) it
also adds a rule:
- the scenario clamps S and never used R1, so the old draft left R1 out;
- the baseline did use R1, and the draft now carries R1 and its assumption ("S responds to U
  within one update").

This is R3 in the original case, not a new finding.

## Tests (`tests/integration/test_logic_model.py`, expected values from the inputs' meaning)

**Repetition:**
- a not-computed repeat is not a fixed point (R1);
- a computed component does not make a partly computed state stable, while its summary stays;
- a complete period-2 cycle is still recognised;
- a declared input change after the run blocks the claim (R2, 3 steps);
- the same scenario run past the change gives a fixed point from 12;
- a clamp released after the run blocks the claim.

**Relative predictions:**
- the relative draft carries the baseline rule, its assumption and evidence id (R3), while the
  scenario's own dependencies stay clamp-only;
- a rule used on both sides is listed once;
- without a baseline, the result is as before;
- listing order changes nothing.

The bounded `unknown_each_step` case already in the suite still passes.
