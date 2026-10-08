# Model–observation link v0, review r1

This review closes three gaps found in the first version (`148b259`):
- a model result whose fields contradict one another was compared;
- a readout reference that conflicts with the mapping's was only a finding;
- recorded categorical values could not be compared at all.

The original records are not changed. `SPEC.md`, `expected.md`, `cases.py`, `results.json`,
`run.json` and `README.md` in the parent folder still match its `SHA256SUMS`. All 15 original
cases rebuild byte-identically, `comparison_id` included.

`cases.py` here builds every new input from the original builders. Every call goes to
`compare_model_observation` (or `run_logic_model`) on `build_server()`. A and B are synthetic
category names; they stand for nothing.

## Scope correction

The work order for v0 named T1–T3 as **categorical** cases:
- T1: `true → A`, `false → B`; model A, observed A; a conditional match.
- T2: model A, observed B; a conditional mismatch.
- T3: model {A, B}, observed A; partial.

The first version recorded T1–T3 as **numeric change** cases instead (increase/decrease/no_change
from ratios under a `DecisionRule`). It did not say so, and the observation side had no path for
recorded categories. Those numeric cases are kept as they were. The categorical cases asked for
are C1–C3 below.

## Reproduced before the fix (`148b259`, product path)

| Input | Before | After |
|---|---|---|
| T3 with the `no_change` paired group dropped | `consistent` | refused: `paired.groups must place each of the 2 cases once; missing [1]` |
| T3 with the paired groups empty | `inconsistent` | refused: `paired.groups … missing [0, 1]` |
| T3 with a group naming case position 99 | `partial` | refused: `paired.groups name case positions [99], outside 0..1` |
| T7c (1 of 4 cases explored) with `paired.applies_to: all_cases` | `consistent` | refused: `paired.applies_to is 'all_cases', which the scenario and baseline sides' applies_to do not support` |
| T1 with `readout_spec.reference: untreated` (mapping `versus: B`) | `comparable`, `consistent`; only the finding `mapping_reference_differs_from_readout_spec` | `correspondence_unresolved`; no result |
| Categorical A, table `active→A`, `inactive→B` | refused: `'A' is not a state observed value (['absent', 'present'])` | with `observed_vocabulary: [A, B]`: compared |

Each stage that blocked these inputs before the fix:
- **R1:** nothing blocked them. The model result was read as given.
- **R2:** the mapping reader reported the difference as a finding. Comparability did not use it.
- **R3:** the link validator refused, because a state claim's observed values were fixed to
  present/absent.

## R1: the model result must agree with itself

`_select` now checks the one window target it selects, before anything is compared:
- **Case labels:**
  - the labels are distinct;
  - their number equals `cases_explored`, which is at most `cases_total`;
  - `exploration_complete` holds exactly when the two counts are equal.
- **Group coverage:** every group's positions are in range, and each case appears in exactly one
  group. This applies to:
  - the scenario groups;
  - the baseline groups, against `cases`, or against `baseline_cases` when not paired;
  - the paired groups.
- **Pairing:**
  - a baseline is present exactly when `pairing.status` is not `no_baseline`;
  - paired directions are present exactly when `pairing.status` is `paired`.
- **Scope:**
  - `paired.directions` equal the union of the groups' directions;
  - a side's `applies_to` agrees with `exploration_complete`;
  - `paired.applies_to` is `all_cases` only when both sides are.

A contradiction is refused, naming the field (R1a–R1m). Valid results are not refused:
- `not_paired`;
- `no_baseline`;
- incomplete exploration;
- values not computed;
- the stored ERK record.

An empty set of model values is a valid result. It is reported as `insufficient`, not refused.

**What this does not do:**
- It does not re-run the model.
- It does not sign the result or keep a ledger.
- It does not check that the hashes match the content. A hash identifies a result; it does not
  verify it.

## R2: a reference conflict holds the comparison

**When this applies:** `readout_spec.reference` and `mapping.versus` are both given and differ
after trimming and case folding.

**What is reported:**
- `comparability` is `correspondence_unresolved`;
- the reason names both fields and both values:
  `readout_spec_reference_differs_from_mapping_versus (readout_spec.reference='untreated', mapping.versus='B')`;
- `result`, `explored_result`, `relation` and `if_accepted` are all null;
- the observation and its finding are kept.

**What does not change:**
- The researcher's acceptance of the correspondence does not override the conflict (R2b).
- The same reference written differently compares normally (R2c).
- `compare_research_observations` keeps its behaviour: there the difference is still a finding.
- Other findings do not block a comparison.

## R3: categorical observations

The link states the categories explicitly in `correspondence.observed_vocabulary`, and the table
maps model state values to those categories. It is only for a `state` claim.

**Which readings are used:** a reading is used only when all three hold:
- its quality is valid;
- it is not a bound;
- its `value_type` is categorical, which the existing `Measurement` sets for a string value.

**Which readings are counted but not used:**
- a below-detection, excluded or missing reading;
- a number.

**What is not done:**
- nothing is converted to a number or to below-detection;
- nothing is binned;
- no synonym is inferred.

| Case | Model | Observed | Result |
|---|---|---|---|
| **C1** | {active} → A | A, A | `comparable`, `single_match`, **consistent** |
| **C2** | {inactive} → B | A, A | `outside`, **inconsistent** |
| **C3** | {active, inactive}, two case groups | A | `partial`, **undecided** |
| **C4** | {active} | C (not in the vocabulary) | `insufficient`; `category_outside_declared_vocabulary` |
| **C5** | {active} | A, excluded B, missing, below detection | consistent on A; `left_out` {excluded, missing, below_detection: 1 each} |
| **C6** | {active} | A, B | `insufficient`; `replicates_disagree` |
| **C7** | {active} | 2.0, 2.2 (numbers) | `insufficient`; `left_out` {not_categorical: 2} |
| **C8** | table names A, no vocabulary | — | refused, pointing to `observed_vocabulary` |
| **C9** | table names C, vocabulary [A, B] | — | refused, naming `observed_value 'C'` |
| **C10** | vocabulary on a change claim | — | refused |

`observation_meaning` is `declared_category`, and the readings used are echoed in
`observed_categories`.

**Limits of the categorical support:**
- One category per observation.
- Replicates that disagree are not combined.
- A category's meaning is only what the table states. Nothing about biology follows from the
  match.
- Categorical **change** claims are not supported.

## Order

The model result can list its cases in another order, with every group index remapped. The
table and the observations can be reversed. Comparability, relation, result, reasons and needs
are unchanged, and each case label keeps its model values (O1: T3; O2: C3).

## Code

- `model_observation.py`:
  - adds `_check_window` and `_check_cover`;
  - adds the reference-conflict reason;
  - adds `observed_vocabulary` to the correspondence and `observed_categories` to the result.

  A link without a vocabulary hashes as before.
- `observe.py`: `read_mapping` takes an optional set of categories, used for a state mapping.
  `_classify_category` reads the readings as written. `compare_observations` never passes
  categories, so its behaviour is unchanged.
- **Reused:** `Measurement.value_type` and `MeasurementQuality` from `core/experiment.py`,
  `read_mapping` and its arm, time-point and quality handling. No new statistics or thresholds.
