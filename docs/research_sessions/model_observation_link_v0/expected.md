# What each test must check (written before the code)

The cases are synthetic contract inputs: a model window with chosen classes or directions, and
`ExperimentRun`s with chosen readings. They test the code's contract and show no biological
performance.

**Synthetic model** (`run_logic_model`, product path):

| | Treatment `T` | Baseline `B` | Case unknowns |
|---|---|---|---|
| Rules | `X(next) = U`, `U` input on | `U` off | none |
| X in window 2–4 | all_active | all_inactive | — |
| Paired directions | {increase} | | |

**Variants:**
- **Multi-direction:** an oscillator with an unknown initial value, giving directions
  {increase, no_change} or {decrease, increase}.
- **Same state:** both sides active, giving {no_change}.
- **Incomplete exploration:** `max_cases` set below the number of cases.

**Observation:** one run with arms `{"arm": "T"}` and `{"arm": "B"}`. Unit `ratio`, assay
`synthetic`, rule ratio:
- increase at or above 1.5;
- decrease at or below 0.67;
- no change between 0.9 and 1.1.

## Cases

| | Input | Must return |
|---|---|---|
| **T1** | Model change {increase}. Observation ratio ≥ 1.5, classified `increase`. Table `increase → increase`; window and baseline correspondences stated; scope includes the experiment. | `comparable`; `single_match`; `consistent`; `scientific_validity_checked` false; correspondence echoed with `stated_by`. |
| **T2** | As T1, but the observation is classified `decrease`. | `comparable`; `outside`; `inconsistent`. The output contains no refutation of a hypothesis; only the linked ids are echoed. |
| **T3** | Model change {increase, no_change} (multi-direction run). Table maps both to the same-named observed values. Observation `increase`. | `comparable`; `partial`; `undecided`; not `consistent`. Per-case groups kept. |
| **T4** | Model change {no_change}: both sides active. Observation `increase`. Table has only `increase → increase`. | `correspondence_unresolved`, reason `model_value_without_correspondence`. No result. The observation record is kept: values and class `increase`. Same-word entries are not assumed. **T4b:** `asks: magnitude` gives `outside_model_representation` with need `richer_model`, even if data are complete. |
| **T5** | State claim; the model scenario is all_inactive. Observation readings below detection, read as analytical `absent`. Table `active → present` only. | `correspondence_unresolved` (`model_value_without_correspondence`). The meaning is reported as analytical detection. Nothing says biological absence or model error. |
| **T6** | Readings normalised to PBS (unit `ratio_to_PBS`); arms U0126, DMSO, PBS. Mapping reference is DMSO, `versus` "DMSO". | Only the U0126 and DMSO arms are read; PBS rows are not. The same readout at another time point is not mixed in. **T6b:** a host-proposed reference correspondence is held, with `if_accepted` given separately and no result. **T6c:** `baseline_stands_for` ≠ `mapping.versus` gives `correspondence_unresolved`. |
| **T7** | Some readings missing or excluded. **T7b:** no rule. **T7c:** exploration incomplete. **T7d:** model values not computed. | **T7:** readings left out and counted, the comparison made on the usable ones. **T7b:** `insufficient`, need `state_or_review_correspondence`, observation kept. **T7c:** `explored_result` given, `result` `undecided`, `applies_to` `explored_cases_only`. **T7d:** `insufficient`, `model_values_not_computed`. |
| **T8** | An unknown target, a repeated table key with two values, a mismatched run hash, a mismatched window. | Each is refused with a message naming the field. Table order changes nothing. The same input gives the same output, including `comparison_id`. Inputs are unmodified after the call. |

## ERK regression (`logic_biology_v1`, `logic_window_v0`, `erk_pmek_measurement_v0`)

**Model.** The M2 KRAS window record for pMEK (stored `window_results.json`): scenario
`all_active`, baseline `all_active`, {no_change} in all 32 cases. Scenario names are taken from
`prereg/case.json`. The model is not re-run.

**Observation.** HCT116 Fig 6B values from `extracted.json`:
- U0126 50 µM, 1 value: the treatment arm;
- DMSO, 1 value: the reference arm;
- PBS = 1 is the normalisation reference, not an arm.

Unit `ratio_to_PBS`. The time point is 24 h, from the results text and not from the file; the
record says so.

| Link | Must return |
|---|---|
| **E1:** `asks: magnitude` | `outside_model_representation`. Observation kept: 6.0086 against 1.1092, both PBS-relative. Model groups kept. |
| **E2:** `asks: category`, no table entry for `no_change` | `correspondence_unresolved`. Nothing classified is turned into agreement or disagreement. With no `DecisionRule` declared, the observation is also not classified, and `needs` lists both. |

The absolute detection class stays unknown and is listed in the record's notes. It is not a
precondition of describing the normalised values.
