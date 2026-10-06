# Review r1: re-measurement

These were produced by `remeasure.py` at `fe6cf1b`, with `src/` clean.

- `measure.json`: sizes, times and agreement with the full paths, from the unchanged
  `../measure_erk.py`. The byte counts are the same as in `../measure.json`:
  - window 166,952;
  - summary 2,167,341;
  - full 7,324,129.

  Only the times differ.
- `compare.json`: the 16 ERK targets against `../window_results.json`. Cases, pairing,
  groups, classes, direction sets, run hashes and request hashes are all the same.
- The re-measured `window_results.json` was byte-identical to `../window_results.json` (sha256
  `3ffb6ccd263436d312d7e89a37a467b9137673116135c31927c45d4c68dd53d3`). It is not stored twice.
