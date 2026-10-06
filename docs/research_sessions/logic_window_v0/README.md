# Window summary v0: the same run, read over a range of steps, in a smaller response

## What was built

`run_logic_model` takes `view: "window"` with `window: {first, last, targets}`. It summarises
the run it just computed, from the same case paths and the same case pairing; there is no second
simulator. Per target and side it gives:

- **Within one case.** Cases are grouped by window class (`all_active`, `all_inactive`,
  `both_values`, `partly_not_computed`, `not_computed`). Each group carries its known values and
  not-computed steps, and names its cases by position in `window.cases`.
- **Across cases.** Two fields:
  - `across_cases`: same class or differs by case;
  - `identical_paths`: the paths themselves. Same class is not same path: 0101 and 1010 are both
    `both_values`.
- **Against a baseline with the same unknowns.**
  - Each case's set of per-step directions over the window, grouped; for example
    `{increase, no_change}` is kept as a set.
  - The union of those sets.
  - `applies_to`: all cases, or explored cases only.

  With different unknowns, no case is paired and no direction is given (`not_paired`).
- **Range.**
  - `constant_from` on each side;
  - `declared_change_after_window`;
  - the engine's own `repetition`, unchanged.

Per-step fields (`summary`, `differences`, `paired_differences`, `readouts`) come back `null`.
They are named in `omitted`, with the view that returns them. Final-step dependencies are kept
for the targets only.

- `run_sha256` is the same under every view.
- `window.request_sha256` identifies the window request.

A call without a window is unchanged:
- the existing suite passes, including the byte-identical rerun of `logic_biology_v1`;
- drafts are the same with or without a window (tested).

The spec (`SPEC.md`) and hand cases (`hand_cases.json`) were committed before the code
(`ec31994`). The amendment at the end of `SPEC.md` records the two size changes made after the
first measurement. The meaning of every field stayed the same.

## What it is not

It is a summary of a computation, not a measurement model. It does not offer the ordinal
"inactive < intermittent < active", and it does not say:
- that `both_values` is an intermediate level or a cycle;
- that a constant window is a fixed point;
- that a group's size is a probability;
- that two equal Boolean states are equal measured levels.

These limits are in `window.limits`.

## Tests (`tests/integration/test_logic_window.py`, 32)

The expected values come from the hand traces, or from separate code over the full view's paths.

| | Case | What it checks |
|---|---|---|
| 1 | H1 | always active or always inactive; a readout target |
| 2 | H2 | the state changes within one path |
| 3 | H3 | constant paths that differ by case |
| 4 | H4a, H4b | 0101 vs 1010 gives {decrease, increase}; 0101 vs 0101 gives {no_change}, with every class the same |
| 5 | H5a, H5b | partly and wholly not computed; an `undetermined` paired step |
| 6 | H6 | exploration limit: 1 of 4 cases, `explored_cases_only` |
| 7 | H7 | the baseline expands another unknown: `not_paired`, both sides still summarised |
| 8 | H8a, 9 refusals | a one-step window; reversed, past `steps`, negative, unknown, repeated, empty or ambiguous targets; a window without the view; the view without a window |
| 9 | H9 | constant window with an input change declared after it: `declared_change_after_window`, repetition `not_assessed` |
| 10 | ERK M1/M2 × KRAS/BRAF | every class per case and side, and every paired direction set, equal to an independent recomputation from `view: "full"` |

Also tested:
- listing order of components, rules and targets changes nothing;
- the run hash is shared across views, and the request hash differs between windows;
- the dependencies kept are exactly the summary view's entries for the targets.

## The ERK case: size and time (`measure_erk.py` → `measure.json`)

**Setup.** The input is `logic_biology_v1/prereg/case.json`, unchanged: M1 and M2, KRAS and
BRAF, 24 steps, window 18–24, all four readouts. Each comparison is called once per view on
`build_server()` at `8ebb303`, with `src/` clean. Bytes are `json.dumps` of the structured
content, the same serialization as `logic_biology_v1/run_case.py`. MCP text blocks are measured
separately.

| Run | full | summary | window | window / full | window / summary |
|---|---|---|---|---|---|
| M1 KRAS | 1,812,604 | 522,445 | 40,786 | 2.25% | 7.81% |
| M1 BRAF | 1,810,340 | 521,773 | 40,683 | 2.25% | 7.80% |
| M2 KRAS | 1,808,398 | 519,671 | 42,741 | 2.36% | 8.22% |
| M2 BRAF | 1,892,787 | 603,452 | 42,742 | 2.26% | 7.08% |
| **Total, structured bytes** | 7,324,129 | 2,167,341 | 166,952 | 2.28% | 7.70% |
| **Total, MCP text-block bytes** | 10,353,297 | 2,814,941 | 249,900 | 2.41% | 8.88% |
| Calls | 4 | 4 | 4 | | |
| Seconds, total of 4 (varies by run) | 0.85 | 0.39 | 0.59 | | |

- **Same answers.** In all 16 target comparisons, the window gives the same answers as the
  independent recomputation from the full paths (`window_agrees_with_full_paths`). The run hash
  is the same across the three views.
- **Not faster.** The window call is slower than summary: it runs the same computation, and then
  groups. The saving is in what is sent, not in compute.
- **What is left in about 41 kB:** mostly final-step provenance, kept on purpose.
  - Dependencies on both sides, and relative dependencies, for the targets: about 25 kB. These
    are the rules, evidence ids and assumptions behind the final values.
  - The engine's per-case `repetition`: about 4.5 kB.
  - The window itself: about 6.7 kB.
- **Size history.** Before the amendment, with labels repeated and every component's dependencies
  sent, a window response was about 59 kB.
- **Not compared.** The 1.8 MB recorded in PR #38 is not set against these numbers. The
  comparison above is the same input, code and serialization, on full vs window.
- **Not converted.** Bytes are not tokens or cost, and nothing here makes a prediction better.

**What the window says for M1 KRAS** (`window_results.json`):
- **pMEK:** treated `all_active` in all 32 cases; untreated `both_values` in all 32; paired
  directions `{increase, no_change}` in every case.
- **pERK and pRaf-1:** `all_inactive` against `both_values`, with `{decrease, no_change}`.
- **Ras-GTP:** `all_active` on both sides, with `{no_change}`.

This is the same information the r0 strict reading took from about 1.8 MB of paths. As before,
it is not read as a measured level.

## Live host

Not run (미실시). The host's `run_logic_model` in this session still offers views `summary` and
`full` only, with no `window` parameter, so it is the previous server. No reconnection or
deployment was attempted.

## Files

- `SPEC.md`: written before the code; amended after the first measurement, with the amendment
  marked.
- `hand_cases.json`: hand traces written before the code.
- `measure_erk.py` → `measure.json`: sizes, times, agreement, commit.
- `measure_erk.py` → `window_results.json`: the `window` part of the four responses, with model
  and run hashes. No full or summary response is stored.
- `SHA256SUMS`.
