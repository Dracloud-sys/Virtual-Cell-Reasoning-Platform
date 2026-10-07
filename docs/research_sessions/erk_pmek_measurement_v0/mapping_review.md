# pMEK: what the data show, what the models computed, and what connects them

This is a retrospective review of how the measurements map to the model, for one readout. It is
not an independent test. Everything here was read after the models were fixed in
`logic_biology_v1/prereg/` (`d37c0b4`). Nothing here changes those models, their scenarios,
their 24 steps or their 18–24 window.

## Inputs

**Model outputs**, reused and not re-run. They come from `logic_window_v0/window_results.json`.
The run hashes equal those in `logic_biology_v1/results.json`.

| Run | Treated (MEKi) window | Untreated window | Paired directions, all 32 cases |
|---|---|---|---|
| M1 KRAS (`6b324d1a…`) | `all_active` | `both_values` | {increase, no_change} |
| M2 KRAS (`b9a06b4b…`) | `all_active` | `all_active` | {no_change} |
| M1 BRAF (`4ba0b18e…`) | `all_active` | `all_active` | {no_change} |
| M2 BRAF (`67cc14a3…`) | `all_active` | `all_active` | {no_change} |

The window classes and directions describe logical steps and cases. They are not time,
fractions or levels.

**Observations.** P1–P9 are in `measurement_record.json`. Numbers marked B come from the
authors' normalised source data (`extracted.json`). Numbers marked D are the host's readings
off the figure.

## Three layers, per comparison

### K1. KRAS lines (HCT116, SW480): pMEK with a MEK inhibitor against untreated

**1. What the data show**
- **Higher pMek after U0126 at mid doses** (P1, level B, 24 h; one or two values per dose; no
  statistics):
  - HCT116: up to ×6.0 at 50 µM;
  - SW480: up to ×3.8 at 20 µM.
- **Unchanged at low doses:** 0.5–1 µM U0126 sits within the control range (P2).
- **Far below control at the highest doses** (P3):
  - HCT116 at 100 µM;
  - SW480 at 50 and 100 µM.
- **Higher within 30–60 min after 1 µM AZD6244:**
  - P6: B, one series;
  - P7: D, mean ± s.d. of 3.

  The s.d. at 120 min is wide.
- **This is a qualitative direction, and it depends on dose.**

**2. What the models computed**
- M1: the untreated window is `both_values`, the treated window `all_active`. Directions
  {increase, no_change} in every case.
- M2: both windows `all_active`. Directions {no_change}.

**3. Assumptions needed to connect them**
- **(a) Which dose the model's "MEKi on" stands for.** The model's inhibitor is one ideal,
  complete block. The data rise at some doses, not at others, and fall at the highest. Picking
  the doses that rose would be choosing the observation to fit the model. No dose is fixed by
  the data or by the pre-registration.
- **(b) For M1: does `both_values` read as a level between "absent" and the treated level?**
  This is still unverified (see B below).
- **(c) Is the untreated pMek "present"?** That decides between "both active" (M2) and an
  absent → present change. The values are ratios to PBS or to untreated, so untreated is 1 by
  construction. Its distance from the background is not reported.

**What can be compared**
- **The data's direction:** confirmed qualitatively, at the doses and times above.
- **M1:** only conditionally, under (a) and (b).
- **M2:** the category comparison (active → active, no_change) against a measured several-fold
  rise is a disagreement *only if* untreated pMek is present and a rise within "present" is
  counted as a change. The size of the rise cannot be compared under either model.

### K2. KRAS lines: the drop at the highest doses

| | |
|---|---|
| Data | P3, level B: far below control at 100 µM (HCT116) and at 50–100 µM (SW480). |
| Models | One inhibitor level; nothing on dose. |
| Connection | None. The authors name possible causes and test none of them: unspecific effects, inhibition of MEK phosphorylation at high doses, a changed phenotype. One of these would break the model's intervention assumption that the inhibitor does not block RAF → MEK phosphorylation. |
| What can be compared | Nothing. The record keeps it as a limit on that assumption. |

### K3. KRAS lines: the untreated level over time

| | |
|---|---|
| Data | P9, levels D and E: without AZD6244, mean pMek stays at about 1.2–1.4 at 30, 60 and 120 min. These are population means of 3 replicates. |
| Models | M1's untreated path changes from step to step (`both_values`; cycles of period 2 or 6). M2's untreated path is constant (`all_active`). |
| Connection | A constant population mean does not separate three possibilities: cells that each oscillate out of phase; cells that differ from one another; and a steady intermediate activity. Logical steps are not minutes. |
| What can be compared | Not M1. M2's constant untreated state is not contradicted, but that is not support either. |

### B1. BRAF lines (HT29, RKO): pMEK with a MEK inhibitor against untreated

**1. What the data show**
- **HT29:**
  - 6B (P4, level B): at the control level up to 10 µM U0126;
  - 6D (P8, level D): at about 1 with 1 µM AZD6244 up to 120 min.
- **RKO, 6D (P8, level D):** at about 1 with AZD6244 up to 120 min.
- **RKO, 6B (P5, level B):** below its controls at *every* U0126 dose. It is 0.39–0.63 at
  0.5–10 µM, against 1.04–1.17. There are one or two values per dose and no statistics.
- **All BRAF lines at ≥20 µM:** far below control.

**2. What the models computed:** both models give `all_active` → `all_active`, {no_change}.

**3. Assumptions needed:** the same (a) and (c) as K1. Equal Boolean states would also have to
be read as an unchanged level.

**What can be compared**
- HT29 (6B ≤ 10 µM, 6D) and RKO in 6D: compatible with no_change, under that reading.
- RKO in 6B: a decrease the models do not produce. It is a single-condition series with no
  test. The inhibitor (U0126, not AZD6244) and the time (24 h, not ≤ 2 h) differ from 6D.

## What changes for the earlier records

This review records new information, row by row, against r0 and r1. Those files are not edited.

| Row | Earlier | Now, with the source data and figure |
|---|---|---|
| B01 (6B, KRAS increase) | r0: M1 strict 미결정, M1 ordinal 부합, M2 불일치; r1: 미결정 / 조건부 양립 / 불일치* | Kept. The data confirm the increase in HCT116 and SW480 (P1), but only at 5–50 µM, not at 0.5–1 µM or at the top doses. The comparison stays conditional on (a)–(c). |
| B02 (6B, BRAF "no increase") | r0 부합; r1 조건부 양립 | **Limited.** The text's "no increase" holds. At the data level, RKO is below control at every U0126 dose (P5), which no_change does not produce. "Compatible" holds for HT29 and not for RKO in 6B. |
| B03, B04 (high-dose drop) | 비교 불가 / 비교 제한 | Kept as not comparable. One correction to the text: HCT116 is at its maximum at 50 µM and drops only at 100 µM (P3), so "exceeding 20 µM … in all cell lines" is not exact. |
| B08 (6C, "rises within 1 h", line not named in the spans read) | 비교 불가 | **New.** The source data and figure name SW480 and HCT116 (P6), so the line is now known and the observed direction is an increase. This is information found after r0 and r1. It does not reclassify them. A model comparison would be the same as K1. |
| B09, B10 (6D) | B09: r0 부합, r1 조건부 양립; B10: r0 미결정 / 부합 / 불일치, r1 미결정 / 조건부 양립 / 불일치* | Kept. The figure shows the KRAS increase, with a wide s.d. at 120 min, and BRAF at about 1 (P7, P8). |
| r1 `series` labels | taken from the text | Confirmed: B01–B04 are Fig 6B, B09–B12 are Fig 6D. Fig 6B has no error bars; the legend's "three replicates" belongs to 6D. |

## Not verified

Each of these is still an assumption:
- that "MEKi on" stands for any particular dose or time;
- that untreated pMek in KRAS lines is "present", that is, clearly above background;
- that a rise within the present range counts as a change, or as no change;
- that an intermittent logical path reads as an intermediate population level;
- that 6B, 6C and 6D can be pooled (they are separate experiments with different inhibitors,
  times and replicate numbers);
- that the RKO decrease in 6B is reproducible.
