# Conditional intervention prediction v0: reference case

**Date** 2026-10-04. **Base** `b56583d` (PR #36 merged into main).

This is an engine check on an abstract circuit, not a biological experiment.
- `U` is an effective external input, `S` an intermediate state, `P` a state of interest.
- The two rule sets are candidates the host stated; they model no named molecule.
- "Wash" is not read as `U = 0`, and "inhibitor" is not read as `S = 0`.

Order of work:
1. `SPEC.md`, `case.json` and `expected_by_hand.json` were written first, with every state of
   both models traced by hand.
2. `virtualcell.simulation.logic` was written next.
3. `run_case.py` ran the case through the MCP tool `run_logic_model`, the host's path, and
   compared every hand value. **24 of 24 matched** (`hand_check.json`).

## The models

| | rule for S | rule for P |
|---|---|---|
| A, input-dependent | `S(next) = U` (R1) | `P(next) = S` (R2) |
| B, self-maintaining | `S(next) = U` (R1) | `P(next) = S OR P` (R2) |

**Run settings:**
- Synchronous update, 6 logical steps. A step is not an hour or a day.
- Initial state `S = P = active` unless a scenario says otherwise.
- `U` active over the whole run unless clamped.

## 1. What was computed, from which rules (no expected value was entered)

The host gave rules, an initial state and clamps. The engine computed every state. In the paths
below, each row is a state index t = 0…6, written as `U S P`:

| scenario | A | B |
|---|---|---|
| s1 input on | `111` at every step | `111` at every step |
| s2 `U` clamped off from t=1 | `111 011 001 000 000 000 000` | `111 011 001 001 001 001 001` |
| s3 `S` clamped off from t=1 | `111 101 100 100 …` | `111 101 101 101 …` |
| s4 `U` off at t=1–2, then released | `111 011 001 100 110 111 111` | `111 011 001 101 111 111 111` |

How removing the input propagates in A (s2):
- U goes off at t=1;
- S follows at t=2;
- P follows at t=3.

Each link is one update. That says how many updates the chain takes, not how long anything
takes.

## 2. Same model, different interventions (each against s1)

**Model A:**
- s2 and s3: `R_P` at step 6 reads `decrease`.
- s4 (released): `no_change` at step 6, although P was off at t=3–4. A difference at one step
  and none at another are both kept; `differences` lists P at t=3 and t=4.

**Model B:**
- s2, s3 and s4: `R_P` is `no_change` at every step.
- What differs is only `U` and `S` themselves.

**Repetition:**
- Every scenario reaches a fixed point after inputs and clamps stop changing.
- For s4, inputs stop changing at t=3; A repeats from t=5 and B from t=4.
- That is a repeat within 6 updates, under clamps held to the end. It is not a claim about any
  cell.

## 3. Where A and B agree and where they differ

**Same:**
- every value under s1;
- `U` and `S` in every scenario, since R1 is the same rule;
- P in s5a after t=0.

**Different:**
- P after the input is removed (s2), after S is clamped off (s3), and during the transient (s4):
  A loses P, B keeps it.
- What keeps P in B is computed from R2 (which reads P itself) and from the initial P. Its
  `dependencies` for P at step 6 list `initial:P`, `initial:S`, `rule:R1`, `rule:R2`, the
  input segment and the clamp. That is what the value was computed from. It is not a claim
  that R2 is the only or minimal cause.

## 4. What could not be decided, and why

**s5c: S clamped off from t=0, P unknown initially, baseline the same without the clamp.**

| | P at step 6 | R_P vs baseline |
|---|---|---|
| A | inactive in both cases | `decrease` |
| B | `differs_by_case` | `undetermined` |

In B:
- Pairing cases by the same initial P gives `decrease` when P starts inactive, and `no_change`
  when P starts active.
- So B's outcome here is set by an initial value nobody knows. The Prediction draft is
  therefore `not_predicted`, with `unresolved` saying why.

**s5a: P unknown, input removed.** P is the same in both cases from t=1 in both models, because
S was active at t=0 and R2 reads it. Here, then, the unknown initial P does not change the
outcome. That holds only because S starts active.

Case counts (1 and 1) are counts of logical cases, not probabilities.

## 5. What the result depends on

**On the rules R1 and R2 as stated.**
- Their `assumptions` are carried into every Prediction draft.
- Their `evidence_ids` are empty here; with ids, they would still be listed as not validated.

**On the ideal clamps.** "U off" means the model input is exactly inactive. That a wash removes
an effective input completely is not shown.

**On synchronous update.** This is how the rules are computed, not a statement that a cell's
processes happen together.

**On the initial state.** For example, B keeps P in s2 only because P (or S) was active at t=0.

## 6. What applying this to cells and measurements would need

**Measurement link.**
- `R_P` here is an abstract identity mapping (P read as itself), and is not an assay.
- A requested readout with no mapping is returned as `not_derivable` (here `alpha_SMA_IF`), and
  the run still completes.
- What is needed, per readout:
  - the state it reads;
  - the method and condition;
  - the mapping rule;
  - that mapping's basis.

**Grounds for each rule:** sources and conditions under which the relation holds. Using one here
would make it a candidate with evidence ids, still not validated.

**Real scenarios:** what a wash or an inhibitor actually achieves, as measured, instead of an
ideal clamp.

**Time:** a model that relates updates to durations. None exists here, so no time is computed.

**Not done here:** fitting to real data, or evaluating prediction performance. A computed
`increase` or `decrease` is a direction relative to a baseline of the same model, never a fold
change.

## Files

| File | What |
|---|---|
| `SPEC.md` | the specification and test plan, written before the code |
| `case.json` | the two models, eight scenarios, four comparisons, one abstract readout |
| `expected_by_hand.json` | hand-traced paths, repetition, readout directions and summaries |
| `run_case.py`, `run.json` | the run through `run_logic_model`, with hashes and the code revision |
| `results.json` | every run (paths, final states, repetition, dependencies) and comparison (differences, paired, readout, draft) |
| `hand_check.json` | 24 hand values against computed values |
