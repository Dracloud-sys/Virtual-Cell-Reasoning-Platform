# N1: the Fig 4B Ras-activity record

**Conclusion first.** The record does not fit N1's purpose:
- Fig 4B's source data, figure and legend contain **only HCT116 and SW480** (both KRAS-mutant),
  each with AZD6244 against DMSO.
- **There is no BRAF-mutant treatment-vs-control comparison in what was read.**

So the path of separating M1 and M2 by Ras-GTP in BRAF-mutant lines ends here for this record.
This is a check of whether the data suit the question. It is not a judgement update, and it says
nothing for or against M1 or M2. No model was run and nothing was compared.

## Question

N1, as corrected in `observation_decision_update_v0/revision_r1`: does the authors' Fig 4B source
data contain a MEK-inhibitor treatment-vs-control comparison in a BRAF-mutant line? If so, at
what level could it be compared with the models?

**Paper:** Fritsche-Guenther et al. 2011
- doi 10.1038/msb.2011.27, PMC3130559;
- licence CC BY-NC-SA 3.0.

## What was read

| | How | Checked against |
|---|---|---|
| `msb201127-df4B.txt`, all 7 lines | Host cache from 2026-10-06. The official location returned **404** on 2026-10-08, recorded as a failure of that location, not an absence of data. | md5 `5b20422c…` equals the package manifest (fetched 2026-10-08) |
| Figure 4 (A–C) and its legend | PDF page 7 rendered at 110 dpi and **looked at** | PDF md5 equals the manifest |
| Legend text, methods ("Ras activity assay", "Immunoblotting"), the results paragraph citing 4B | Cached Europe PMC XML | Legend matches the one printed on the page |

The official publisher page was not tried: the cached file already matched the manifest checksum
(`sources.json`).

## What the record contains

| Item | Found | Source |
|---|---|---|
| Cell lines | HCT116, SW480 | file lines 4–7; legend; figure |
| Treatment / control | AZD6244 / DMSO. The blot also has an untreated lane ("ut") that the file does not quantify. | file col. 2; figure lanes |
| Time | 2 h | methods; results text |
| Concentration | Not stated for this assay. The methods' general list gives "1 µM AZD6244". | methods |
| Analyte, readout | GTP-bound Ras by GST-Raf-1-RBD pulldown, then western blot | legend; methods; file line 2 |
| Values | HCT116 DMSO 1 (SD 0), AZD6244 0.9 (SD 0.04); SW480 DMSO 1 (SD 0), AZD6244 0.81 (SD 0.21) | file lines 4–7 |
| Unit, normalisation | Mean normalised integrated density, normalised to DMSO. Whether a loading control was applied to the pulldown is not stated. | file line 3; methods |
| Replicates | A summary (mean, SD) only. "Three assays"; whether these are independent biological replicates is not stated. | file; legend |
| +GTP / +GDP | Positive and negative controls of the pulldown assay, not treatment arms. No rows in the file. | legend; figure |
| BRAF treatment vs control | **Absent** | file, legend, figure |

**Data levels:**
- **The file:** the authors' summary of quantified blots. It is not raw instrument signal.
- **The figure:** shows the same means and SDs; no values were read off it.
- **The text:** a qualitative statement ("no increase of Ras activation … in the Ras-mutated
  cells").

**Not moved across panels.** Two other panels of Figure 4 involve BRAF V600E, but neither
measures Ras-GTP, so neither is used here:
- **4A:** HT29 with U0126, read as phospho-Raf-1;
- **4C:** CaCo2 with B-Raf V600E and AZD6244, read as pMek.

No new average, renormalisation or test was made.

## Outcome (branch A of the corrected N1)

**What follows:**
- In the data read, there is no BRAF treatment-vs-control comparison of Ras-GTP.
- The KRAS values are not used as observations for the BRAF-condition models.
- M1 and M2 are neither supported nor refuted.

**Not claimed:** that no such data exist anywhere in the paper or in other public sources. Only
Fig 4B's file, figure, legend and linked methods were read.

**No model comparison.** There is no BRAF observation to compare. The KRAS Ras-GTP result is
already the paper's O5 statement (B06 in `logic_biology_v1`), and comparing it again is outside
this check.

## Relation to D1 and N1

**Known before:**
- D1 (`observation_decision_update_v0`, as corrected in its revision r1): M1 kept as the working
  base; O1 and `M2_R_RAS` held. The feedback-site question was open.
- `sources.json` there listed df4B as "Fig 4B, Ras activity", unread.
- The results text had already reported Ras activity only for Ras-mutated cells (B06).

**New from this check:**
- The file, figure and legend show the record holds only the two KRAS lines, with AZD6244 vs
  DMSO at 2 h.
- The values are DMSO-normalised summaries of three unspecified assays.
- The official file location now returns 404.

**D1:** unchanged. Nothing here bears on it. The holds stay holds, and M1 stays the working base
for the same reasons as before.

**N1's feasibility:** closed for this record. It cannot serve the purpose it was chosen for.

**One next action (proposed, not performed):** record the remaining question as needing a
measurement, rather than searching further records. The question is Ras-GTP in a BRAF V600E line
with and without a MEK inhibitor, against vehicle.
- Before any comparison with the models, it would still need the category, intervention, time and
  sample-level correspondences named in revision r1.
- Dose, time and replicate number are not fixed here; nothing in the records gives a basis for
  them.

## Files

| File | |
|---|---|
| `extract.py` → `extracted.json` | the file's 7 lines: header strings and data rows with line numbers, values as strings |
| `check.json` | each item with its source; the outcome |
| `sources.json` | every location used or tried, status, checksums, counts |
| `SHA256SUMS` | |
| Test | `tests/integration/test_rasgtp_fig4b_check_v0.py`. The source-dependent part needs `RASGTP_FIG4B_SOURCE_CACHE` and is skipped, not passed, without it. |
