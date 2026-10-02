# C1: one public quantitative dataset, from raw file to next experiment

**This is one case, not an evaluation.** It is the first time the observation path read real
measurements, not the host's own synthetic ones.

## The answer, first

**Observations used.**
- Zenodo 8342247 (CC-BY-4.0): human gingival fibroblasts seeded on Ti40Zr10Cu36Pd14 bulk
  metallic glass (BMG) and on Ti6Al4V specimens, read with alamarBlue at 24 h and 48 h.
- 22 wells were used, each traced to its sheet and cell: per time point 4 TI-CTL, 5 TI-BMG and
  2 AB wells, in `results/observation_inventory.json`.
- 6 POLY wells were not used: no prediction or check names that group, and its role is not
  stated anywhere.

**Why they could be compared with the predictions.**
- Unit (RFU), assay string and time point match the plan's readout.
- Each time point was read on one plate in one read, so 24 h and 48 h are never compared with
  each other: the reads were at 29.2 °C and 35.1 °C.
- The data's reference group is labelled `TI-CTL`, not "Ti6Al4V". The label was not edited. A
  `reference_correspondence` records that TI-CTL is the plan's Ti6Al4V, with its basis (the
  record's description and the paper both name Ti6Al4V as the control surface). It is marked
  **host_proposed**.
- A host-proposed correspondence is held. Here that changed nothing: no value was classified
  even before the reference step.

**What was held.**
- **BMG vs Ti6Al4V was not classified at either time point.** Under the declared rule, the
  treatment × reference combinations disagree:
  - 24 h: 10 of 20 increase, 7 between bands, 3 no change *(corrected in revision 2; first
    written as 9 / 8 / 3, a hand count — the recorded output always said 10 / 7 / 3)*;
  - 48 h: 18 of 20 increase, 1 between bands, 1 no change.
  At 24 h all three no-change combinations involve the fifth BMG well (P23); the between-band
  ones involve several wells. At 48 h both non-increase combinations involve the fifth BMG
  well (S8).
- **The background assumption is not established.** The check "Ti6Al4V wells read above the
  reagent-only wells" disagrees on both days. *Corrected in revision 2, per time point:* at 24 h
  TI-CTL L22 (1641 RFU) is **below** both 24 h AB wells (1743, 1756); at 48 h TI-CTL O7
  (1595 RFU) is **within** the 48 h AB range (1581–1624). The first version merged the AB values
  of the two time points into one range. What AB contains is itself an unaccepted,
  host-proposed reading of the label.
- **Not a single combination reached the declared decrease band** (lowest 0.926). The host notes
  this. It is not a classification of "no toxicity".

**Next action proposed.** The host holds every hypothesis and keeps the goal: judge BMG
cytocompatibility against Ti6Al4V. The hold is on this one readout, not a failure of the
question.

*Resolve from the records*, no new experiment needed:
1. Accept or reject TI-CTL = Ti6Al4V and AB = reagent only.
2. Say whether the specimen was in the read well.
3. Say whether wells are independent specimens, and whether the same specimen was read at 24 h
   and 48 h. If so, declared pairs could be used.
4. Resolve where the AB wells were (the grid says C7–C8, the plate-area line says H8–H9).
5. Reconcile "triplicate" in the paper with the 4 and 5 wells in the export.

*New experiments*, with the rule, the background handling and the unit declared **before** the
read:
- **E2:** cell-free dye on a BMG specimen, on a Ti6Al4V specimen and alone, on the same plate
  and in the same read. It checks "the BMG specimen does not change alamarBlue fluorescence
  without cells".
- **E3:** DNA per specimen in the same wells, to separate cell number from activity per cell.

## Revision 2: what is observed, what the rule returned, what is conditional, what to do next

Revision 2 keeps every C1 input, plan, rule and output unchanged. It adds a description of each
arm to the comparison, and corrected decisions (`decisions_r2.json`, revising `decisions.json`).
It reads the same data again into `results_r2/`.
- `results_r2/descriptive_check.json` recomputes every number below straight from the CSV.
- That file also confirms that no status, classification, reference link or outcome changed
  from `results/`.

### 1. What the data say directly

Recorded RFU per group and time point, labels as written. `n` is the number of recorded values,
not of independent biological replicates; the record does not say which wells are separate
specimens.

| time | group | n | values (sheet!cell order) | median | min | max |
|---|---|---|---|---|---|---|
| 24 h | TI-BMG | 5 | 2805, 3052, 2905, 3012, 2343 | 2905 | 2343 | 3052 |
| 24 h | TI-CTL | 4 | 1641, 2307, 2491, 2393 | 2350 | 1641 | 2491 |
| 24 h | AB | 2 | 1743, 1756 | 1749.5 | 1743 | 1756 |
| 24 h | POLY | 3 | 3075, 3261, 3276 | 3261 | 3075 | 3276 |
| 48 h | TI-BMG | 5 | 3610, 4625, 3968, 3579, 2495 | 3610 | 2495 | 4625 |
| 48 h | TI-CTL | 4 | 1595, 1894, 2105, 2695 | 1999.5 | 1595 | 2695 |
| 48 h | AB | 2 | 1581, 1624 | 1602.5 | 1581 | 1624 |
| 48 h | POLY | 3 | 5678, 5509, 4835 | 5509 | 4835 | 5678 |

- **Same time point only:**
  - At 24 h, three TI-CTL wells are above both AB wells and L22 (1641) is below both.
  - At 48 h, three are above and O7 (1595) lies between the two AB wells.
  - No well is called an outlier or removed.
- **Missing values:** none recorded. **Detection limits:** none stated by the source, so none
  declared. **Bounded or flagged values:** none. Nothing was replaced or imputed.
- **Not used:** POLY, because no prediction or check names it and its role is not recorded.
- **Not compared:** 24 h with 48 h, because the reads were at 29.2 °C and 35.1 °C.
- No background was subtracted, no well dropped, no time points merged, no threshold changed.

### 2. What the declared rule returned, and its limits

The policy is `all_combinations`: every treatment reading is set against every reference
reading, and a class stands only if every combination agrees.

| comparison | combinations per class | result |
|---|---|---|
| 24 h TI-BMG vs TI-CTL | 10 increase · 7 between bands · 3 no change | not classified (`combinations_disagree`) |
| 48 h TI-BMG vs TI-CTL | 18 increase · 1 between bands · 1 no change | not classified |
| 24 h TI-CTL vs AB (background check) | 6 increase · 2 no change | check not established |
| 48 h TI-CTL vs AB | 4 increase · 2 between bands · 2 no change | check not established |

- These are counts of combinations. They are not replicates, a success rate, a probability or
  statistical evidence; 18/20 is not "90% likely".
- "Not classified" means **no single class under this rule**. It does not mean "no difference
  between groups", and it does not mean "the data carry no information": the table above is
  that information.
- **The bands themselves have no basis for this assay.** They were fixed earlier (d7d8bc2) for
  synthetic development. Being older than this dataset does not make them a validated
  criterion for alamarBlue RFU on these specimens. Applying them here was the host's post-hoc
  choice.

### 3. Interpretations to keep, revise or hold, and what they rest on

All four hypotheses are **held** (`decisions_r2.json`). What each hold rests on:

| hold rests on | why it blocks |
|---|---|
| TI-CTL = Ti6Al4V, host-proposed | a change prediction is not compared on an unaccepted correspondence |
| background not established | raw ratios to TI-CTL are not ratios of cell signal |
| interference untested | a higher BMG signal is what H_more and H_int both predict |
| cell number vs activity not measured | even a classified increase would not say which |

**How much each correspondence rests on.**

| correspondence | what the record shows | level |
|---|---|---|
| TI-CTL → Ti6Al4V | The Zenodo description names the two surfaces, Ti6Al4V and Ti40Zr10Cu36Pd14 BMG. The paper (sec3.3) calls Ti-6Al-4V the control surface. The label pairs "TI" with "CTL". | documented by inference: the record never states "TI-CTL is Ti6Al4V" |
| AB → reagent only (no cells) | Two wells labelled "AB" in the plate grid, read with the plate. Neither the record nor the paper defines them. | the label alone: the host's reading |

- If a researcher accepts either correspondence, that is acceptance of **this analysis's
  mapping**, not an independent confirmation of how the original experiment was run.
- `accepted_by` stays empty here because no researcher has accepted anything.
- `if_accepted` stays a conditional result only. It is empty in C1 because no value was
  classified.
- Facts the record cannot show are not put to the user to approve: whether the specimen was in
  the read well, and whether wells are separate specimens. Only the authors' records can
  settle them.

**What resolving each cause would change, and what would remain.**

| cause | resolving it changes | still remaining |
|---|---|---|
| A. group/context unconfirmed | accepting TI-CTL = Ti6Al4V makes the link `researcher_accepted`; accepting AB = reagent only makes the background check a compared check | both comparisons stay unclassified because of B; the specimen-in-well and independence questions need the authors' records, not an acceptance |
| B. combinations disagree under `all_combinations` | only a different declared policy, or pairs with a basis in the record, could give a single class; neither exists | nothing in the record pairs a BMG specimen with a Ti6Al4V specimen, so B stays |
| C. bands have no basis for this assay | a researcher declares bands, policy and background handling, with a reason, before any re-read | a class from today's bands describes synthetic bands, not this assay |
| D. biological measurements missing | E2 decides interference; E3 separates cell number from activity per cell | even a clean, classified increase stays consistent with both H_more and H_int until E2 |

### 4. Next actions, in order, and the decision each one changes

None of these has been run.

1. **Ask the data creator what AB contains and whether the specimen stayed in the read well.**
   - This decides whether the background check can be read at all.
   - It decides whether E2 must come before any interpretation of BMG > Ti6Al4V (if the
     specimen was in the well, it must).
2. **Have the researcher declare the comparison before re-reading:** bands with a reason,
   policy, background handling, and the unit of replication.
   - This decides whether a classification would mean anything for this assay.
   - Without it, B and C stay.
3. **E2, cell-free specimen read.**
   - This decides the interference assumption.
   - If BMG raises the signal without cells, the raw BMG > Ti6Al4V cannot count toward H_more.
4. **E3, DNA per specimen**, only after E2.
   - It separates H_tox/H_eq from more cells vs more activity per cell.
   - Read before interference is known, alamarBlue per DNA is not interpretable.

No new measurement is added beyond E2 and E3.

### Corrections made in revision 2

- **24 h class counts:** 10 / 7 / 3, not 9 / 8 / 3.
- **Background relation, per time point:**
  - 24 h: L22 is below both 24 h AB wells, not within the AB range.
  - 48 h: O7 is within the 48 h AB range.
- **H_more reason:** both non-increase 48 h combinations involve BMG well S8. No Ti6Al4V well
  decides it.

**Scope of input.** For this one file, the explicit extraction (`extract.py`) and the ingestion
through `DatasetSpec` are **done**. Interpreting an arbitrary workbook automatically, or
generalising the input step, is **not implemented**.

## What each part did

| | done by |
|---|---|
| downloading the file, checking its md5 against Zenodo's | host (`source.json`) |
| transcribing typed per-well values, keeping sheet!cell and labels; refusing formulas; checking the duplicate 48 h copy | `extract.py` (development record, not product code) |
| tidy CSV → `ExperimentRun` (28 observations, ids `bmg_alamar_tidy.csv:rowN`, QC `valid`, no rows rejected) | existing `DatasetSpec` / `ingest_file` |
| plan, hypotheses, predictions, assumption check, mappings, correspondences, rule choice | host (`plan.json`, `rules_and_mappings.json`) |
| paper sections read, ids server-issued (`server_retrieved`) | `read_evidence_source` |
| comparability, classification per combination, check outcome, dependants, scope | `compare_research_observations` via `build_server()` (`results/comparison.json`) |
| keep / revise / hold and next experiments | host (`decisions.json`; corrected in `decisions_r2.json`) |

**Order, stated plainly.** The plan, the hypotheses, the mappings and the choice of rule were all
written **after the values had been seen**. The rule's bands were fixed on 2026-09-25 (d7d8bc2)
for synthetic development, before this dataset was found, and are reused unchanged. Applying
them to this assay is post hoc (`time_order: post_hoc`). Nothing here is a pre-declared test,
and no statistic or significance is computed. The authors' ANOVA "not significant" and this
record's "not classified" are different statements.

## What the real data exposed in the product, and what changed

1. **Every table ingested through `DatasetSpec` read as `assay_mismatch`.**
   - Cause: ingestion writes its import procedure (`declared_tabular_import_v1`) into each
     measurement's `provenance.method`, and the comparison preferred measurement-level method.
   - Fix: for an imported measurement, the assay is now taken from the run, where the spec
     declares it. A regression test goes through `ingest_table`. The ingestion code itself is
     unchanged.
2. **A plan reference could only be matched by a condition value spelling it.**
   - Real labels (`TI-CTL`, `AB`) never will. Renaming them is not allowed.
   - `ObservationMapping.reference_correspondence` (`ReferenceCorrespondence`) now records which
     observed group stands for a plan reference, on what basis, stated by host or researcher,
     accepted by a researcher or not.
   - The resulting `reference_link` is one of:
     - `structural`: code-checked;
     - `researcher_accepted`: compared;
     - `host_proposed`: held, with `if_accepted`, what it would give, counted nowhere;
     - `conflicting`: the record names another group, reference or experiment; held;
     - `declared_only`: a bare name; held.

## Files and hashes

- `source.json`: record, licence, URL, md5/sha256 of the workbook. The workbook itself is not
  committed.
- `bmg_alamar_tidy.csv`: sha256 `18990f80…3db60d`, 28 rows. `extraction_report.json` holds the
  per-group counts and the duplicate check.
- `dataset_spec.json`, `plan.json`, `rules_and_mappings.json`, `decisions.json`: their sha256
  values are in `results/manifest.json`.
- `results/`:
  - `draft_check.json`: the plan checked; all cited ids `server_retrieved`.
  - `comparison.json`: revision `rev-f504a3f151e819d6`, prior plan sha256 `7ec6aba9…`.
  - `observation_inventory.json`.
  - `manifest.json`.
- `results_r2/` (revision 2): same inputs, `decisions_r2.json`, arm summaries added; revision
  `rev-bfd31fefbaff0cbe`, same prior plan sha256. `descriptive_check.json` is the independent
  recomputation and the no-change check against `results/`, produced by `check_r2.py`.
- `host_call.json`: one call from the connected host. It was refused because the host server
  predates `reference_correspondence`. The flow above ran on the product path in-process.

## Not claimed

- That BMG is or is not cytocompatible.
- That TI-CTL is Ti6Al4V or that AB is reagent only. Both are host-proposed and unaccepted.
- That wells are independent replicates.
- That this one case shows the platform helps research in general.
