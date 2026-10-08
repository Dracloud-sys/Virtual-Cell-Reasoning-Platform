# Model–observation link v0: specification

Written on 2026-10-07, before the code, together with `expected.md` (the meaning each test must
check). The tests check those meanings; their expected values were not copied from the
implementation's output.

## What it does

It compares one claim a model run computes with one claim an observation set measures. The
comparison is made only under an explicit correspondence that says how one is read as the
other. It returns:

- the comparability;
- where comparable, a conditional result;
- in every case, what was kept and what is missing.

It decides nothing for the research plan: keep, revise and hold stay the host's.

**v0 scope:**
- one model result: a `run_logic_model` window response, or its identifying subset;
- one observation set: `ExperimentRun`s read through one existing `ObservationMapping`;
- one readout;
- one treatment-against-reference comparison.

The model's cases and the observation's readings are kept as they are. Neither is reduced to
one value.

## Reused, not restated

| Piece | From |
|---|---|
| Observation selection: arms, time point, assay, unit, quality, pairs, reference link, state reading, change classification under a `DecisionRule` | `research/observe.py`. Its arm-reading part is moved into one function, `read_mapping`, used both by `compare_observations` and by the link. Its behaviour is unchanged. |
| Reference correspondence and its hold rule (`host_proposed` held; `if_accepted` reported separately) | `ReferenceCorrespondence`, `_reference_link` |
| Thresholds | `DecisionRule` only. None is invented. |
| Model classes and paired directions per case | `WindowRun` of `simulation/logic.py`, as computed. The model is never re-run here. |
| Identity | `model_sha256` and `run_sha256` from the run. A hash is an identity check, not proof of authenticity or of biological validity. |

New code: `research/model_observation.py`, holding two contracts (the link and its result)
and one function. The MCP entry point is `compare_model_observation`.

`compare_research_observations` is not extended, because it reads every mapping against the
plan's predictions and needs a `ResearchReport`. A link has no plan prediction. Calling it
would mean inventing a hypothesis and a prediction. Both entry points call the same
`read_mapping`, so there is one observation reader.

## Input

### `model_result`

Either a full `run_logic_model` response with `view: "window"`, or these fields copied from
it:
- `model_id`, `model_sha256`, `run_sha256`;
- `scenario` (the scenario's name) and `baseline` (the baseline's name, or null);
- `cases_explored`, `cases_total`, `exploration_complete`;
- `window`.

### `link`

**The selection** pins one model claim:

| Field | Meaning |
|---|---|
| `model.run_sha256`, `model.model_sha256` | Must equal the result's. |
| `model.scenario`, `model.baseline` | Must equal the result's. |
| `model.window` (`first`, `last`) | Must equal the window that was requested. |
| `model.target` | Must be exactly one of the window's targets. |
| `model.claim` | `state`: the scenario's window class. `change`: the paired directions against the baseline. |

**The observation** is an `ObservationMapping` (existing), plus an optional `ReadoutSpec` for
its assay and unit.
- The normalisation reference is part of the measurement (its unit or name). It is not a
  comparison arm.
- The comparison arm is `mapping.reference`. Nothing is chosen because a value is "relative to"
  it.

**The correspondence** says how the model claim is read as the observation claim:
- `table`: pairs `{model_value, observed_value}`.
  - Model values: `active` and `inactive` (state); `increase`, `decrease` and `no_change`
    (change, per step, paired by case).
  - Observed values: `present` and `absent` (state; the existing analytical meaning: a valid
    non-zero reading, or one recorded below the producer's detection limit); `increase`,
    `decrease` and `no_change` (change, classified under the mapping's `DecisionRule`).
  - **No word is mapped to itself unless the table says so.** A model `no_change` (two equal
    Boolean states) is not a quantitative `no_change` (a value inside a declared band).
- `asks`: `category` (default), or `magnitude`. A Boolean model computes no magnitude, so a
  magnitude question is outside the model's representation.
- `window_correspondence`: the stated basis for reading the model window as the observation's
  time point and conditions. Without it, the claim is not compared.
- `baseline_stands_for`: for a change claim, the plan reference the model's baseline stands
  for. Compared as written with `mapping.versus`.
- `applies_to_experiment_ids`, `basis`, `evidence_ids`, `assumptions`, `stated_by`
  (host | researcher), `accepted_by` (researcher | null).

  Acceptance is the acceptance of an analysis assumption. It is not a validation. It does not
  override a conflict.

**Linked research records:** `hypothesis_ids`, `experiment_ids`, `decision_ids`. They are echoed
back and nothing is changed in them.

## Order

1. **Integrity.** Each of these is refused with a message naming the field and value: a wrong
   or unparseable record, a mismatched identity, a mismatched scenario, baseline or window, an
   unknown or repeated target, a change claim with no baseline, a table entry outside the
   claim's vocabulary, or one model value mapped to two observed values. Nothing is replaced by
   a first or last candidate.
2. **Observation reading.** `read_mapping` runs, and its full record is kept whatever happens
   next.
3. **Meaning and scope.** These are checked before any comparison. Nothing is compared first
   and warned about afterwards.
   - `outside_model_representation`: the question asks a magnitude.
   - `correspondence_unresolved`, with one of these reasons:
     - the claim forms differ (state against change);
     - the correspondence does not apply to this experiment;
     - the window correspondence is not stated;
     - the baseline correspondence is not stated, or differs from `mapping.versus`;
     - the observation's reference link is not comparable, or is host-proposed (held);
     - a model value has no table entry.
   - `insufficient`, with one of these reasons:
     - the observation is not classified (its own reasons are kept);
     - the model has values that are not computed or undetermined in the window;
     - the model side is not paired.
4. **Comparison**, only when comparable:
   - **M** is the set of observed-vocabulary values the model's values map to, over every
     explored case and every window step, kept per case group too.
   - **o** is the observed class.
   - **`relation`:**

     | Condition | `relation` | `result` |
     |---|---|---|
     | M = {o} | `single_match` | `consistent` |
     | o ∉ M | `outside` | `inconsistent` |
     | o ∈ M and M has more than one value | `partial` | `undecided`, never consistent |
     | o = `indeterminate` | `between_bands` | `undecided` |

   - **With incomplete exploration:** `explored_result` is the result above, and `result` is
     `undecided` for all cases.
   - **Host-proposed reference held:** `if_accepted` gives the result the comparison would
     have if the reference were accepted. It is never counted as the result.

## Output (`ModelObservationComparison`)

- **Identity:** `link_id`, `link_sha256`, `observations_sha256`, the model identity (ids and
  hashes; `window.request_sha256`), and `comparison_id` (a hash of all inputs).
- **`model_claim`:**
  - the form;
  - the model values per case group, with positions into `window.cases`;
  - the union of those values;
  - the cases explored and total, and `applies_to`.

  Its meaning is "Boolean model state" or "per-step paired Boolean direction".
- **`observation`:** the `ReadoutComparison` from `read_mapping`, with its meaning:
  - `analytical_detection` (present/absent as recorded);
  - `quantitative_change` (classified under the declared rule);
  - `not_classified`.
- **Comparability:** `comparability` and `reasons`, plus `needs`, a subset of:
  - `check_record`;
  - `state_or_review_correspondence`;
  - `richer_model`;
  - `more_measurement`.

  The host chooses among these; the code proposes no experiment.
- **Result:** `relation`, `result`, `explored_result`, `if_accepted`, `applies_to`.
- **Correspondence:** the correspondence used, as given (who stated it, whether it was
  accepted, its evidence and assumptions), and `scientific_validity_checked: false`.
- **Links:** the linked research ids, echoed.
- **`limits`.**

## Not done

No threshold, background correction, renormalisation, mean or test is computed.

None of these mappings is made unless the table states it:
- below detection → biological absence → Boolean inactive;
- a positive value → active;
- the same word → the same claim.

Pairs come only from declared pairs. Model cases are never paired with observations by order.
No case count, step count or arm combination becomes a replicate count or a probability. The
model, the plan, the runs, the mapping and the link are never modified.
