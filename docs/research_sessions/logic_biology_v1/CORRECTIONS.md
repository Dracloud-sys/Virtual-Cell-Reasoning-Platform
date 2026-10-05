# Corrections to this record

The r0 files are kept byte for byte as recorded at `346c1b6` (`SHA256SUMS`, `prereg/SHA256SUMS`):
- `README.md`;
- `observations.json`;
- `results.json`;
- `comparison.json`;
- `run.json`;
- `run_case.py`;
- `host_check.json`;
- `prereg/`.

This file says where they are corrected or narrowed. Details and the re-reading are in
`revision_r1/README.md`.

**`README.md` section 7, "Representation: synchronous Boolean update of a negative loop".**
- M1's rules with KRASmut = 1 and MEKi = 0 have no fixed point at all, under any update scheme
  (`revision_r1/fixed_points.json`).
- Only the periodic path is the synchronous scheme's.
- The constant vehicle pMek in the text is a population measurement. It is not an observation
  about individual cells, and how the logical path maps to it is not established.

**`observations.json` B02, B06 (and B13, B15).**
- "No increase" was recorded as `no_change`; the limit was only in a note.
- r1 keeps the wording as `no_increase` (only an increase ruled out), and the recorded
  direction unchanged.
- Agreement with the model's `no_change` is 조건부 양립, not an exact match.

**`README.md` sections 5–6 and `comparison.json`, M2's 불일치 for B01 and B10.**
- These need the assumption that two active Boolean states mean no measured change.
- They are disagreements under the current model and identity readout. They are not a
  refutation of feedback at RAS.
- "Only O1 discriminates the feedback site" holds only under the KRAS always-active
  assumption, the complete-veto rules and that readout.

**`README.md` section 5, M1 ordinal 부합 (B01, B05, B10).**
- The ordinal rule was pre-registered, not post hoc.
- Its premise (intermittent = intermediate measured level) is unverified.
- These rows are 조건부 양립 and do not resolve the strict reading's 미결정.

**Tallies.**
- The 16 rows are statements, several from one series. The tallies are the r0 classifier's
  output, not hit rates or a model ranking.
- r0's "비교 불가" mixes three causes: out of model scope; no scenario or mapping; not secured
  in the spans read. The last does not mean the paper has no such data.

**`README.md` section 8, the next action.** It merged two layers:
- a computed-path summary (an output candidate);
- a measurement model (a separate biological question).

They are separated in `revision_r1/README.md` section 5, with the first thing to check for this
case in section 6.
