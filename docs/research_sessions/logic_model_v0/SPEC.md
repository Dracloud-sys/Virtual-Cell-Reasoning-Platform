# Conditional intervention prediction v0: specification

Written on 2026-10-04, **before** `virtualcell.simulation.logic` existed, together with the
hand-traced tables in `expected_by_hand.json`. The tests compare the engine against those
tables; the tables were not copied from engine output.

The question this answers is: *if this candidate model and these conditions held, what would
follow?* It does not say whether the model is true of any cell.

## Why not `SimulationEngine`

`simulation/engine.py` has a `CellState` of `dict[str, float]` layers with `time: float`, and a
`step(state, dt: float, environment: dict[str, float])` protocol. A logic model has three
things that interface cannot carry without loss:
- values that are only active or inactive;
- values that are unknown and must not become 0;
- steps that are not time, so there is no `dt` to give.

Filling `CellState` would turn "unknown" into a number and "step 1" into a duration. So the
protocol is left untouched, and the logic model is a separate, small representation in
`simulation/logic.py`.

## Model

- **Components.** Each has an `id` and a `kind`:
  - `input`: given by the scenario, never by a rule;
  - `internal`: given by exactly one rule.

  Active and inactive are abstract states the model declares. They are not a concentration, a
  detection or an expression level.
- **Rules.** `{id, target, expr, evidence_ids, assumptions, stated_by, note}`, one per internal
  component.
  - **Expressions** are structured JSON, never strings: `{"const": true|false}`,
    `{"var": "<component id>"}`, `{"not": e}`, `{"and": [e, ...]}`, `{"or": [e, ...]}`.
  - **Allowed operators:** these and no others. No eval or exec, and nesting depth is limited.
  - **What is refused:**
    - a rule naming an undeclared component;
    - a rule for an input;
    - two rules for one component.
  - **A missing rule is not refused.** The component is reported `not_computed` from step 1
    on, never filled with inactive and never held at its previous value.
  - **Self-maintenance** must be a rule that reads the component itself, e.g.
    `P(next) = S OR P`.
- **Update:** `synchronous` only. Any other value is refused with a reason; it is never
  silently treated as synchronous.

## Steps

States are indexed `t = 0 … N`. `x_0` is the initial state. For every internal component `c`,
`x_{t+1}[c] = rule_c(x_t)`: every rule reads the same previous state, so the order in which
components or rules are listed cannot matter.

A step is a logical update, not an hour or a day. No half-life, clearance or recovery time is
computed.

Inputs are given per state index by the scenario as segments
`{start, end (inclusive, or null for open), value}`. Each value is one of:
- `true` / `false`;
- `"unknown"`: one unknown value held for the whole segment, the same throughout a case;
- `"unknown_each_step"`: an independent unknown value at each index of the segment.

An index that no segment covers has no input value, so anything computed from it at that index
is `not_computed`.

## Interventions (clamps)

`{target, value: true|false, start, end (inclusive or null)}` on an input or an internal
component.

- **Scope:** for every index `t` with `start ≤ t ≤ end`, `x_t[target] = value`. This replaces
  the target's own rule or schedule at those indices, and the clamp wins over the rule.
- **First update affected:** rules computing `x_{t+1}` read `x_t` after clamps are applied, so
  the first update that reads the clamped value produces `x_{start+1}`. A clamp at `start = 0`
  replaces the initial value.
- **Release:** `end` is inclusive. `x_{end+1}[target]` is computed by its own rule (or schedule)
  from `x_end`, which is still clamped.
- **Conflicts:** two clamps on one target with overlapping indices and different values are
  refused as an input error. Order never picks one.
- **The model is not modified.** A clamp is an ideal model intervention; it says nothing about
  whether a wash or a drug achieved complete removal or complete block.

## Unknowns

Unknown initial values and unknown input segments are **expanded into cases**: every
combination of true and false, each case run on its own, every path kept. An unknown keeps its
value for its whole scope within a case.

Values are summarised per component and step as one of:
- `same_in_all_explored`, with the value;
- `differs_by_case`;
- `not_computed`, with the missing rule or input;
- `exploration_incomplete`.

The number of cases giving each value is a count of logical cases. It is never a probability,
a confidence or a success rate. "Same in all" is never said unless every case was explored.

Inside one case, three values are possible: active, inactive, or not computed (because a rule
or an input is missing). Not computed is combined by Kleene's rules: an AND with an inactive
operand is inactive, and an OR with an active operand is active, whatever the not-computed
operand is. Any other combination stays not computed.

## Limits

These are operational limits, not biology:
- at most 32 components;
- at most 100 steps;
- at most 256 cases by default, 4096 at most.

Past the case limit, the first cases in a fixed order are run and the result says the
exploration is incomplete.

## Repetition

Once all inputs and clamps stop changing (the **constant-from** index), a state that repeats is
reported:
- `fixed_point` when it equals the next state;
- `cycle` with its period otherwise.

Before that index, or when an input varies at every step, no stability is claimed. Reaching
`N` is reported as reaching `N`, not as a steady state.

## Baseline comparison

A scenario is compared with a baseline only if the model, initial state and number of steps
are the same.

- **Per component and step:** both single-valued and different gives `differs`; both
  single-valued and equal gives `same`; anything else is `undetermined`.
- **Paired cases:** when both scenarios have the same unknowns, cases with the same
  assignment are also compared one by one.

## What a result depends on

For each component at the final step, the **computed-from** set is traced back through the
unrolled steps:
- every rule evaluated, with the components it read;
- clamps, input segments and initial values.

That is a record of what the number was computed from, not a claim of minimal or unique cause.

Evidence ids and assumptions attached to those rules are listed. They are not validated.

## Readouts

A readout maps one model state to one measured readout. v0 has one mapping:
- `identity`: active reads as `present`, inactive as `absent`, with its basis and assumptions.

How readouts are reported:
- **Without a mapping,** the state is still computed, and the readout is `not_derivable`.
- **Against a baseline at the same step:** `present` vs `absent` gives `increase` /
  `decrease` / `no_change` only when both sides are single-valued; otherwise `undetermined`.
  No fold change is produced.

A computed readout can be turned into a `Prediction` **draft** with basis `assumption`. The
draft's assumptions name the model hash, the rules and the mapping, and its `note` says it was
computed. It is never `evidence_observed` and never a user observation. Nothing is added to any
plan; a host that adopts it goes through `check_research_draft` with `prior_draft` as before.

## Output

Each result carries:
- the model id, version and content hash (computed over components and rules sorted by id, so
  listing order does not change it);
- the rules with their `stated_by`, evidence ids and assumptions;
- the initial state, with its unknowns, and the scenario and baseline;
- the update mode, the steps and the cases explored out of the total;
- the per-step summary, the baseline differences, the dependencies, the readouts;
- what was not computed, what is undetermined and which limits were reached.

The default view leaves the per-case paths and the rule-application trace out. `view: "full"`
includes them.

## Test plan (A-D)

- **A. Rules**
  - and, or, not and constants;
  - an undeclared variable and an unknown operator are refused;
  - a missing rule gives `not_computed`, not a held value;
  - the model is unchanged after a run.
- **B. Update and clamps**
  - every rule reads the previous state;
  - permuting components, rules and segments changes nothing;
  - clamp start, inclusive end and release;
  - a conflicting clamp is refused;
  - no output names a time unit.
- **C. Unknowns and limits**
  - unknown is never inactive;
  - cases are kept per path;
  - same-in-all versus differs-by-case;
  - the case limit gives exploration incomplete;
  - not computed is never reported as maintained.
- **D. Connection**
  - a prediction draft is never evidence;
  - a missing mapping is not derivable, without failing the run;
  - the same input gives the same result and hash;
  - the existing suite still passes.
- **Neutrality:** the same circuit renamed (`X`, `Y`, `Z`) gives the same result. That is a
  check of the shared code, not a biological evaluation.
