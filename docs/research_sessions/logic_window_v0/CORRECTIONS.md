# Corrections to this record (review r1 of PR #39)

These files are kept byte for byte as recorded (`SHA256SUMS`):
- `SPEC.md`, committed before the code at `ec31994`, with its marked amendment;
- `hand_cases.json`;
- `measure_erk.py`, `measure.json` and `window_results.json`, recorded at `8ebb303`;
- `README.md`.

This file says where they are corrected. The re-measurement is in `review_r1/`.

## Both findings reproduced on the product path

Both were reproduced at `a7fd559`, through `build_server()` → `run_logic_model`.

**R1 — same class, different gaps.**
- Rules: `Q(next) = NOT Q`, `P(next) = Q OR Z`; Z has no rule.
- Initial state: Q unknown, Z true, P true.
- Window: 0–3, target P.
- Paths:
  - Q=0: P is `1 1 1 ?`;
  - Q=1: P is `1 1 ? 1`.

Both cases are `partly_not_computed` with known values `[true]`; their not-computed steps are
[3] and [2]. At `a7fd559` `across_cases` said `differs_by_case`.

**R2 — a repeated readout id.**
- Readouts: `R → X` and `R → Y`, where X is always true and Y always false.
- Window: target `R`.
- Result at `a7fd559`: R read X when listed `[Y, X]`, and Y when listed `[X, Y]`. The last
  declaration silently won.

Outside the window the same id was ambiguous too:
- the summary view returned two `R` readouts;
- the draft and relative-dependency lookups are keyed by readout id, so one declaration replaced
  the other there.

## What changed

**`across_cases` now compares `window_class` only.**
- `SPEC.md` ("Across cases") defined `same_class` as "one group". Groups also split on
  `known_values` and `not_computed_steps`, so that definition said "same detailed group", while
  `README.md`, the field description and the tool guidance said "same class". The class meaning
  is now the rule.
- Groups keep the finer split.
- `identical_paths` and `applies_to` are unchanged.
- R1 now gives `same_class`, with `identical_paths: false` and two groups.
- Cases of different classes still give `differs_by_case`. For example, `partly_not_computed`
  against `all_active` (a test).
- A partly computed window is still never `all_active`.

**A repeated readout id is refused, in every view.**
- The message names the id and its two positions in `readouts`, counting from 0.
- This applies to two declarations of the same state as well.
- Nothing is renamed and no declaration is chosen.
- `ReadoutMapping.readout` and the tool guidance now state that ids must be unique.
- Inputs with unique ids are unchanged: the full suite passes, including the byte-identical
  rerun of `logic_biology_v1`.

**Unchanged:** state computation, update, interventions, repetition, drafts, pairing and
directions.

## ERK, re-measured (`review_r1/`)

`review_r1/remeasure.py` runs `../measure_erk.py` unchanged, writing to `review_r1/`. It then
compares the 16 targets with the first record (`review_r1/compare.json`):
- cases;
- pairing;
- every group;
- every class;
- every direction set;
- the run and request hashes.

All are the same. In the ERK case every side had one group, so `across_cases` could not move.

The sizes are in `review_r1/measure.json`, with the same serialization. They are recorded and
were not a pass condition.
