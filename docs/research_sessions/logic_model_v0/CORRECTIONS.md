# Corrections to this record

`SPEC.md`, `case.json`, `expected_by_hand.json`, `results.json`, `README.md` and the rest of the
files in `SHA256SUMS` are kept byte for byte as first recorded at `1660785` / `915eb4f`. This
file says where they have been corrected. Details are in `review_r2/README.md`.

- **SPEC, "Repetition."** The section said a state that repeats after the constant-from index is
  reported. It did not say that a state holding a not-computed value is not a known state, or
  that changes declared after the last step count. From review r2:
  - a repeat is reported only between fully computed states;
  - `constant_from` includes changes after the run, and when it lies beyond the last step
    repetition is `not_assessed`, with a reason.
- **SPEC, "Readouts"; README section 5.** A draft against a baseline named only the scenario's
  rules. It now names both sides' rules, with their evidence ids and assumptions, and the run
  returns `baseline_dependencies` and `relative_dependencies`.
- **`results.json`, the drafts' computed-from text (all eight comparisons).** It is now
  written per side.
- **`results.json`, the drafts' assumptions for `s3_S_off` and
  `s5c_S_off_from_0_P_unknown` (A and B).** These lacked R1's assumption, which the baseline
  used. The state values, repetition, readouts and expected directions recorded there are
  unchanged by the fix (`review_r2/case_compare.json`).
