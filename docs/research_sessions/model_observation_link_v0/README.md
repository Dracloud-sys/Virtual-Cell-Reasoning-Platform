# Model–observation link v0

This compares one claim a model run computes with one claim observations measure, only under a
correspondence that someone states explicitly.

- **Spec:** `SPEC.md`, written before the code (`4ebbd23`).
- **Expected meanings:** `expected.md`, also written before the code.
- **Cases:** `cases.py` builds every case on the product path and writes `results.json` and
  `run.json`. The tests use the same builders.

Cases T1–T8 are synthetic contract inputs. They test the contract, not biology.

## Results

All calls go to `compare_model_observation` on `build_server()`. The model results come from
`run_logic_model` with view "window"; the ERK case uses the stored window record.

| Case | Input | Comparability | Result |
|---|---|---|---|
| **T1** | model {increase}; observed increase (ratios 2.0 and 2.2 against 1.0); table `increase→increase` | comparable | `single_match`, **consistent** |
| **T2** | model {increase}; observed decrease | comparable | `outside`, **inconsistent** (not a refutation) |
| **T3** | model {increase, no_change} across two case groups; observed increase | comparable | `partial`, **undecided**, never consistent |
| **T4** | model {no_change} (both sides active); observed increase; no entry for `no_change` | correspondence_unresolved (`model_value_without_correspondence`) | none. The observation (increase; 2.0, 2.2 / 1.0) is kept. |
| **T4b** | same, `asks: magnitude` | **outside_model_representation**; needs `richer_model` | none. The data are complete, and more data would not change this. |
| **T5** | model inactive; readings below detection (analytical `absent`); only `active→present` in the table | correspondence_unresolved | none. Nothing about biological absence or model error. |
| **T6** | U0126 against DMSO, normalised to PBS; PBS and the day-2 reading present in the run | comparable | consistent. Only U0126 (day 1) and DMSO (day 1) were read. |
| **T6b** | reference correspondence proposed by the host | correspondence_unresolved (held) | none; `if_accepted` is consistent, reported separately |
| **T6c** | `baseline_stands_for` differs from `mapping.versus` | correspondence_unresolved | none |
| **T7** | one reading excluded, one missing | comparable | consistent on the usable readings; `left_out` {excluded: 1, missing: 1} |
| **T7b** | no `DecisionRule` | insufficient; needs `state_or_review_correspondence` | none; the readings are kept |
| **T7c** | 1 of 4 cases explored | comparable | `explored_result` consistent; `result` **undecided**; `model_exploration_incomplete` |
| **T7d** | model values not computed in the window | insufficient (`model_values_not_computed`) | none |
| **T8** | unknown target, mismatched hash, window or baseline, a conflicting or out-of-vocabulary table entry | refused, naming the field | — |

**ERK regression.** This uses the stored records only; nothing is re-run and no new data are
used.
- **Model:** M2, KRAS, pMEK, window 18–24. The model gives {no_change} in all 32 cases, with
  both sides active.
- **Observation:** HCT116, Fig 6B. U0126 50 µM (6.00862069) against DMSO (1.109195402), both
  relative to PBS, as the authors give them. PBS is the normalisation reference; it is in the
  run and is not read as an arm.
- **The 24 h time point** comes from the results text, not from the source file.

| Link | Comparability | What is kept, and why nothing is computed |
|---|---|---|
| **E1**: `asks: magnitude` | **outside_model_representation**; needs `richer_model` | The values above, and the model's {no_change}. A Boolean model does not compute a size. |
| **E2**: `asks: category`; no entry for `no_change` | **correspondence_unresolved** | Same. No `DecisionRule` was declared for these data, so the observation is also not classified (`no_decision_rule`). Neither gap is filled. |

The absolute detection class of these readings is still unknown (`erk_pmek_measurement_v0`).
It is not needed to describe the normalised values, so it is not made a precondition.

## How each gap is reported

A gap is never reduced to a bare "not comparable". Each kind maps to its own comparability
status and to what would move it:

| Gap | Comparability | `needs` |
|---|---|---|
| A question the model cannot represent (T4b, E1) | `outside_model_representation` | `richer_model`, even when the data are complete |
| No stated reading between the two (T4, T5, T6b, T6c, E2) | `correspondence_unresolved` | `state_or_review_correspondence` |
| Readings, a rule or model values missing (T7b, T7d) | `insufficient` | named by cause |

The `needs` values are `check_record`, `state_or_review_correspondence`, `richer_model` and
`more_measurement`. Which one to pursue is the host's choice.

## Code

**Added:**
- `src/virtualcell/research/model_observation.py`, with:
  - two contracts: `ModelObservationLink` and `ModelObservationComparison`;
  - the input subset `ModelWindowResult`;
  - one function, `compare_model_observation`.
- The MCP tool `compare_model_observation`, with its guidance.

**Reused:**
- `observe.read_mapping`: the arm-reading part of `compare_observations`, moved out unchanged.
  Both entry points call it, and all existing observe tests pass. It supplies the arms, time
  point, assay, unit, quality, pairs, reference link and hold rule, and the `DecisionRule`
  classification.
- `ObservationMapping`, `ReferenceCorrespondence`, `DecisionRule`, `ReadoutSpec` and
  `ExperimentRun`.
- `WindowRun` from `run_logic_model`, with its case groups, pairing and `applies_to`.

**Why a separate tool:** `compare_research_observations` reads mappings against a plan's
predictions. A link has none, and calling that tool would mean inventing a hypothesis and a
prediction.

## Limits

- **v0 scope:**
  - one model result: a window view;
  - one mapping;
  - one readout;
  - one treatment-against-reference comparison;
  - Boolean models only.
- **What a result means:** it holds under the stated correspondence. It is not a scientific
  validation (`scientific_validity_checked: false`). Acceptance of a correspondence is
  acceptance of an assumption.
- **No new thresholds or statistics:**
  - no threshold, mean, test, background correction or renormalisation;
  - no synonym mapping;
  - no pairing by order.
- **The hash check:** a hash identifies a result; it does not authenticate where the result
  came from.
- **Nothing is changed:** no model, plan, run, mapping or decision.
- **Live host:** not checked against the deployed server in this work (see the PR).
