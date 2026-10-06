# ERK case, pMEK readout: how far the measurements and the model can be compared

**Question.** The models' pMEK results are active, inactive, or changing inside the window. How
far can the pMek measurements of Fritsche-Guenther et al. 2011 be compared with them?

**Scope.**
- One readout, pMEK.
- Figures 6B, 6C and 6D of that paper, their legend and methods, the supplement, the
  review-process file, and the authors' source data.
- The models (M1, M2), their scenarios, their steps and their window are unchanged.
- r0 and r1 in `logic_biology_v1/` are unchanged.
- No model was re-run; the stored window results were reused.

This is a retrospective review of how the measurements map to the model. It is not a holdout, a
blinded test or an independent prediction.

## What was obtained

| | Level | Status |
|---|---|---|
| Fig 6B: pMek against U0126 dose (0.5–100 µM), 4 lines, 24 h (stated in the text only) | **B**: the authors' source data file, values normalised to PBS-treated cells | obtained, md5 checked against the package manifest |
| Fig 6C: pMek over 0–240 min after AZD6244, SW480 and HCT116 | **B**: source data file, normalised to one t0 sample | obtained, md5 checked |
| Fig 6D: pMek at 30, 60 and 120 min ± AZD6244 ± cycloheximide/actinomycin D, 4 lines, mean ± s.d. of 3 | **D**: read off the rendered figure; **E**: legend and text | **no source data in the package**. 6D was added during revision. Values are host estimates (`measurement_record.json`). |
| Raw Bio-Plex readings, blanks, standard curve, plate layout | **A** | **not obtained**: not in any file of the open-access package |

The files were found on the NCBI PMC Cloud open-data bucket. The PMC article page returned a
reCAPTCHA challenge, and the Europe PMC image endpoints returned 403 and 500 (`sources.json`).
The PDF page with Figure 6 was rendered and looked at; the figure was not taken from parsed
text. The source-data files themselves are not committed (CC BY-NC-SA 3.0). `extract.py`
downloads them, checks the md5 and copies each value with its line (`extracted.json`). The
output was the same, byte for byte, online and offline.

**Not achieved:** obtaining public raw data (level A). **Achieved:** the review of what was
obtained (levels B, D and E).

## Measured quantity, units, normalisation, replicates, range

**Known:**
- **Species:** MEK1 phosphorylated at S217/S221, on Bio-Plex beads. This is not total MEK and
  not MEK activity.
- **Units:** dimensionless ratios. In 6B, to PBS (= 1); in 6C, to one t0 sample; in 6D, to
  untreated at t0.
- **Replicates:**
  - 6B: one or two values per dose, with no error bars or statistics. The legend's "three
    replicates" belongs to 6D.
  - 6C: one series.
  - 6D: three replicates, unit not stated.
- **Statistics:** none for inhibitor against no inhibitor. 6D reports only "no significant
  difference" between expression-inhibited and non-inhibited feedback, with the test unnamed.

**Not known:**
- blank and background handling;
- whether readings were normalised to protein (BCA was measured; its use is not stated);
- detection range, linearity and saturation;
- catalogue and lot of the beads.

What turns on these unknowns:
- Without the blank, whether untreated pMek is "present" or near background cannot be decided.
  The ratios set untreated to 1 by construction.
- Without range or linearity, the ×6 maximum cannot be placed on the assay's scale.

## The models' pMEK, and what can be compared

Model outputs, from `logic_window_v0/window_results.json`; run hashes equal to
`logic_biology_v1/results.json`:
- **KRAS:**
  - M1: untreated `both_values` → treated `all_active`, {increase, no_change};
  - M2: `all_active` → `all_active`, {no_change}.
- **BRAF:** both models give `all_active` → `all_active`, {no_change}.

Comparison by comparison (details in `mapping_review.md`):
- **KRAS, pMek with the inhibitor.**
  - The data show a qualitative increase. It holds at 5–50 µM U0126 (24 h) and within 30–60
    min of 1 µM AZD6244.
  - It does not hold at 0.5–1 µM, and pMek falls far below control at the top doses.
  - **M1:** conditionally comparable only.
  - **M2:** "no change" disagrees only if untreated pMek is present and a rise within
    "present" counts as a change.
  - **Size of the rise:** not comparable under either model.
- **KRAS, the high-dose drop.** Not comparable; there is no dose in the model. It bears on the
  intervention assumption that the inhibitor does not block RAF → MEK phosphorylation.
- **KRAS, untreated over time.** A constant population mean (6D) does not separate
  out-of-phase oscillation, cell-to-cell difference and a steady intermediate activity. M1's
  changing path is neither supported nor contradicted. Steps are not minutes.
- **BRAF.**
  - Consistent with no_change: HT29 at ≤ 10 µM U0126, and HT29 and RKO with AZD6244 in 6D.
  - **Not consistent:** RKO falls below control at every U0126 dose in 6B. This is new,
    data-level information. It is one or two values per dose with no test, at a different
    inhibitor and time from 6D.

## Earlier interpretations: kept, limited, corrected

No earlier file is edited. The details are in `mapping_review.md`.

- **Kept:**
  - B01 and B10: the KRAS increase, still conditional;
  - B03 and B04: the high-dose drop, still not comparable;
  - B09.
- **Limited:** B02 ("no increase in B-Raf-mutated cells"). Its r1 "conditionally compatible"
  holds for HT29, not for RKO in 6B.
- **Corrected:**
  - The text's "exceeding 20 µM … drop in all cell lines" is inexact: HCT116 peaks at 50 µM.
  - The r1 series labels are confirmed (6B: B01–B04; 6D: B09–B12).
  - B08's cell lines are now known: 6C is SW480 and HCT116. This does not reclassify r0 or r1.

## Mapping assumptions still unverified

- that "MEKi on" stands for any particular dose or time;
- that untreated pMek in KRAS lines is "present" (clearly above background);
- that a rise within "present" counts as a change, or as no change;
- that an intermittent path reads as an intermediate population level;
- that 6B, 6C and 6D can be pooled;
- that the RKO decrease in 6B is reproducible.

## One next action

**Obtain the uncorrected Bio-Plex readings for Fig 6B or 6D: the median fluorescence per well
for the untreated and treated KRAS samples, together with the blank and background wells.**

What the readings could show, and what each outcome would mean:
- **Untreated KRAS pMek is clearly above blank, and treated values lie below the assay's
  upper limit:**
  - untreated pMek can be mapped to "present";
  - the observed rise is a change *within* "present", which a Boolean identity readout cannot
    express;
  - M2's "no change" becomes a limit of the readout's resolution, not a disagreement about the
    category;
  - M1's agreement stays conditional on the intermittent = intermediate assumption;
  - a graded readout mapping would be the next question.
- **Untreated KRAS pMek is near blank:**
  - untreated maps to "absent";
  - the observation is absent → present;
  - both models put untreated pMek in the wrong category: M1 says intermittent, M2 says active;
  - M1 matches only through the ordinal assumption.
- **Not obtainable from public sources:** this was the case here. The readings would need the
  authors' records, and no one was contacted. Every comparison above stays as stated:
  - the direction of the data is confirmed;
  - the models are comparable only conditionally;
  - magnitudes are not compared.

More reading of the published ratios cannot settle this, because untreated is 1 by
construction. It needs the readings themselves. No experiment is proposed, and none was
performed.

## Files

| File | |
|---|---|
| `sources.json` | every location tried, its status, md5, licence and counts. 0 searches, 14 direct fetches, 0 assay documents (no catalogue number to tie a manufacturer document to). |
| `extract.py` → `extracted.json` | Fig 6B and 6C values with file and line, copied as strings. |
| `measurement_record.json` | levels per panel, the 6D figure readings with their uncertainty, the checklist (confirmed or unconfirmed, and what each affects), observations P1–P9. |
| `mapping_review.md` | the three-layer table and the row-by-row note on r0 and r1. |
| `SHA256SUMS` | |
| Test | `tests/integration/test_erk_pmek_measurement_v0.py` |
