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
  - 24 h: 9 of 20 increase, 8 between bands, 3 no change;
  - 48 h: 18 of 20 increase, 1 between bands, 1 no change.
  At 24 h all three no-change combinations involve the fifth BMG well (P23); the between-band
  ones involve several wells. At 48 h both non-increase combinations involve the fifth BMG
  well (S8).
- **The background assumption is not established.** The check "Ti6Al4V wells read above the
  reagent-only wells" disagrees on both days. One TI-CTL well per day (1641 and 1595 RFU) sits
  within the AB range (1581–1756). What AB contains is itself an unaccepted, host-proposed
  reading of the label.
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

## What each part did

| | done by |
|---|---|
| downloading the file, checking its md5 against Zenodo's | host (`source.json`) |
| transcribing typed per-well values, keeping sheet!cell and labels; refusing formulas; checking the duplicate 48 h copy | `extract.py` (development record, not product code) |
| tidy CSV → `ExperimentRun` (28 observations, ids `bmg_alamar_tidy.csv:rowN`, QC `valid`, no rows rejected) | existing `DatasetSpec` / `ingest_file` |
| plan, hypotheses, predictions, assumption check, mappings, correspondences, rule choice | host (`plan.json`, `rules_and_mappings.json`) |
| paper sections read, ids server-issued (`server_retrieved`) | `read_evidence_source` |
| comparability, classification per combination, check outcome, dependants, scope | `compare_research_observations` via `build_server()` (`results/comparison.json`) |
| keep / revise / hold and next experiments | host (`decisions.json`) |

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
- `host_call.json`: one call from the connected host. It was refused because the host server
  predates `reference_correspondence`. The flow above ran on the product path in-process.

## Not claimed

- That BMG is or is not cytocompatible.
- That TI-CTL is Ti6Al4V or that AB is reagent only. Both are host-proposed and unaccepted.
- That wells are independent replicates.
- That this one case shows the platform helps research in general.
