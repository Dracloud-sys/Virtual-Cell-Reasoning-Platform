# Window summary v0 for `run_logic_model`: specification

Written on 2026-10-05, **before** the code, together with the hand-computed cases in
`hand_cases.json`. The tests compare the implementation against those cases; the expected
values were not copied from its output.

## What it is

A summary of what the engine already computed, over a chosen range of logical steps, for
chosen components or readouts. It answers four questions without sending every case path:

1. **Within one case:** is the state in the window always active, always inactive, both, or
   (partly) not computed?
2. **Across cases:** do the cases fall in the same class? Are their paths in the window
   identical?
3. **Against the baseline:** for paired cases, which directions occur at the window's steps?
4. **What limits these answers:** not-computed values, unexplored cases, unpaired cases, and
   declared changes after the window.

It is a summary of a computation. It is not a measurement model. It does not turn:
- an intermittent state into an intermediate level;
- a fraction of steps into a fraction of time;
- a number of cases into a number of cells or a probability;
- two equal Boolean states into equal measured levels.

The ordinal "always inactive < intermittent < always active" is not a reading it offers.

## One computation

There is no second simulator. `run_logic` runs the cases exactly as before. When a window is
requested, the summary is built from the same case paths, and the same pairing the engine
uses for its per-case readout directions: the same case labels, in the same order, from the
same unknowns. The per-step direction is the engine's own `_direction`.

## Request

`view: "window"` together with `window: {first, last, targets}`:
- **`first`, `last`:** state indices, both inclusive, with `0 <= first <= last <= steps`.
- **`targets`:** one or more names. Each is a component id or a readout id from `readouts`.
  - A readout is read through its identity mapping: active reads present.
  - A name that is neither, a name that is both, or a repeated name is refused.
  - Targets are reported sorted by name, so listing order changes nothing.
- A window without `view: "window"`, or `view: "window"` without a window, is refused.

  This keeps a summary and a full result from being mistaken for each other.
- Out-of-range, reversed or unknown requests are refused with a message. Nothing is clipped or
  replaced by a near match.

A call without `window` is unchanged: same fields, same values.

## Classes (per case, per side, per target)

| Class | The values at `first..last` |
|---|---|
| `all_active` | every value computed and true |
| `all_inactive` | every value computed and false |
| `both_values` | every value computed; true and false both occur |
| `partly_not_computed` | some values not computed; `known_values` and `not_computed_steps` say which |
| `not_computed` | no value computed |

- A `partly_not_computed` window whose known values are all true is **not** `all_active`.
- `both_values` says the state changes inside the window on that path. It is not a claim of a
  cycle or a period.
- A constant window is not a fixed point. A one-step window is constant by definition, and says
  nothing about stability.

## Across cases

- Cases with the same class, the same `known_values` and the same `not_computed_steps` are
  grouped, with every case label kept.
- A group's size is a count of logical combinations. It is not a weight or a probability.
- `across_cases`:
  - `same_class`: one group;
  - `differs_by_case`: more than one group.
- `identical_paths`: whether every explored case has the same value sequence in the window.
  Same class is not same path: 0101 and 1010 are both `both_values` and are not identical.
- `applies_to`:
  - `all_cases` when exploration is complete;
  - otherwise `explored_cases_only`.

## Against the baseline

**Pairing.** Directions are computed per case and per step, never by comparing class names.
- `pairing.status: "paired"`: scenario and baseline expanded the same unknown labels, so the
  explored cases carry the same labels in the same order. That is the engine's own condition
  for per-case readout directions. Case *k* of the scenario is paired with the baseline case
  of the same label.
- `pairing.status: "not_paired"`: the explored label lists differ (for example, an input is
  unknown on one side only). No pair is made by position or by a coincidence of names; there
  are no directions, and the reason is given.
- `pairing.status: "no_baseline"`: no baseline. The absolute summary is still returned.

**Per case.** The set of directions over the window's steps, with each step's direction as in
the engine:
- `increase` / `decrease` / `no_change`;
- `undetermined` where either value is not computed.

Cases with the same set are grouped, with their labels. `directions` is the union over the
explored cases. `{increase, no_change}` is returned as it is; no representative is chosen.

**Scope.** With exploration incomplete, the sets are about the explored cases only
(`applies_to: explored_cases_only`). That no `decrease` occurred is not said of the cases not
explored.

## Range and repetition

- `constant_from` (scenario and baseline): the engine's index after which declared inputs and
  clamps stop changing.
- `declared_change_after_window`: true when either side's `constant_from` lies after `last`.
  A constant window then says nothing about what follows.
- Repetition stays the engine's own top-level `repetition`, unchanged. No new fixed-point
  search is made.

## What the window response keeps and drops

**Kept:**
- model and run identity: `model_id`, `model_version`, `model_sha256`, `run_sha256`;
- `window.request` and `window.request_sha256`;
- the scenario and baseline as given;
- unknowns, case counts and `exploration_complete`;
- `final`, `repetition`, `not_computed`, `limits_reached` and `limits`;
- dependencies on both sides, and Prediction drafts if a `hypothesis_id` was given.

  These describe the **final step** (`t = steps`), as before. They are not the window's, and
  the response says so.

**Dropped, and named in `omitted` with how to get them:**
- `summary` (every component at every step);
- `differences` and `paired_differences`;
- `readouts` (every readout at every step, with per-case directions);
- `cases`, `baseline_cases` and `trace`.

These come back as `null`, not as empty lists, so that "not sent" is not mistaken for "none".

**Identity.**
- `run_sha256` is the same as for the same run under any view: a display option does not make
  a different model or run.
- `window.request_sha256` hashes the run hash with the request (targets sorted), so two
  different windows of one run are not confused.

## Limits carried in the window

- A step is a logical update, not time.
- Case counts are counts of combinations, not probabilities.
- Classes and directions are Boolean computations, not measured levels.
- Dependencies and drafts describe the final step only.
