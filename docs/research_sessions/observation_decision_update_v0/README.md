# Observation-driven decision update v0: where the ERK feedback acts

This is a **retrospective decision update on published observations** (공개 관찰을 이용한 후향적
판단 갱신 사례). It is not a holdout, a blinded test or an independent prediction:
- every observation used was already read in earlier records;
- the model outputs are stored records, so the comparison's outcome could be anticipated before
  it was run (`before.json`, `known_before_fixing`).

It connects functions that already exist:
- `compare_model_observation` (PR #41);
- the stored `run_logic_model` window results (`logic_window_v0`);
- the ERK case's records (`logic_biology_v1`, `erk_pmek_measurement_v0`).

Product source changes: **0 lines**.

## 1. Question and D0

**Question (`Q-site`).** Should the case's working base model keep the ERK-dependent feedback
at RAF (`M1_feedback_on_RAF`) rather than at RAS (`M2_feedback_on_RAS`)? What should be checked
next to decide it?

**D0 (`D0-site`)**, as recorded before this work:
- **Decision:** keep M1 as the base model, with M2 as a sensitivity alternative.
- **Recorded in:** `logic_biology_v1` (prereg, README sections 6–7, revision r1) and
  `erk_pmek_measurement_v0`.
- **Why it was reasonable:**
  - M1's RAF-level rule rests on a cited abstract;
  - the paper's own reasoning names RAF-level feedback;
  - O1 (pMEK in KRAS-mutant lines under a MEK inhibitor) is the only scorable question that
    separates the two models. On it, M1 was "conditionally compatible" and M2 "disagrees".
- **Planned next action:** the uncorrected Bio-Plex readings.

`before.json` was committed (`47c411c`) before the comparison was run. It fixes D0, the inputs
and what would re-open D0.

## 2. What was compared

| | |
|---|---|
| Models | M1 and M2, both fixed together in `logic_biology_v1`. Stored windows (`logic_window_v0/window_results.json`, keys `…/KRAS`), not re-run. |
| Comparison and window | `KRAS_MEKi` vs `KRAS_control`; steps 18–24; target pMEK; claim `change` |
| Observation | Unchanged from PR #41's ERK case: Fig 6B, HCT116. U0126 50 µM (6.00862069) against DMSO (1.109195402), both relative to PBS; PBS is not read as an arm. 24 h is from the results text. One value per arm. The 50 µM arm was a post hoc choice in PR #41. |
| Rule | Host-declared: increase at a ratio ≥ 3.0, anchored on the authors' "three- to four-fold" (B01). No no_change or decrease band; below 3.0 is indeterminate. |
| Table | increase→increase, decrease→decrease, no_change→no_change. The last entry reads equal Boolean states as an unchanged measured level: a host assumption. |
| Who stated it | The host. No researcher accepted the table, the rule or the window, dose and baseline correspondences. |

`run_comparison.py` makes two `compare_model_observation` calls on `build_server()` and writes
`comparison.json`. `run.json` holds the commit and the hash of every input.

## 3. What the code returned

| | M1 (`mo-5526e1d7404ba90d`) | M2 (`mo-a13253779baf2030`) |
|---|---|---|
| comparability | comparable | comparable |
| model values | {increase, no_change}: one group of all 32 cases, each case alternating over the window | {no_change}: all 32 cases, every step |
| observed | increase (one ratio, 5.417) | increase |
| relation / result | **partial / undecided** | **outside / inconsistent** |
| explored_result, if_accepted | undecided, null | inconsistent, null |
| reasons, needs | none | none |
| correspondence_accepted | false | false |

## 4. Code vs host, and the premises re-examined

`decision.json` keeps four layers apart:
- **A. What the code checked:** the rows above, under the stated correspondence.
- **B. What the host read into it:**
  - M1 does not predict the rise as a single outcome. Every case alternates, because M1 has no
    fixed point under `KRAS_control`.
  - D0's "M1 is conditionally compatible" came from the ordinal aggregation, which the contract
    does not make.
  - M2's "inconsistent" comes only from the no_change→no_change entry.
  - So O1 by itself does not separate the feedback sites.
- **C. Not yet distinguished:**
  - For M1: whether the alternation reflects a real oscillatory tendency, or only that a
    complete veto with KRAS always on has no steady state.
  - For M2: whether feedback in KRAS lines is not at RAS, or the identity readout cannot express
    a rise within "active".

**Premises re-examined** (three, all part of this comparison):
- **RC1:** the no_change table entry.
- **RC2:** `M1_R_RAF`'s complete veto with KRAS always on.
- **RC3:** MEKi = 50 µM U0126.

## 5. D1 (`D1-site`)

| Target | D1 | Why |
|---|---|---|
| `O1` | **hold** | It gives M1 partial/undecided, and M2 inconsistent only via RC1. It no longer counts for M1 or against M2. |
| `M2_R_RAS` | **hold** | Neither lowered nor promoted. Its own category-level consequence has not been compared with any observation. |
| `M1_feedback_on_RAF` | **keep** | Kept as the working base model. No comparison contradicts it in category. It is no longer kept *because O1 favours it*. |

**Summary:** the base model is kept; D0's justification is revised; the feedback-site question
stays open. The decisions validate as `HostDecision` objects. Their targets are ids defined in
`logic_biology_v1/prereg/case.json`.

## 6. One next action and its branches

**`N1-rasgtp-braf-record`** (`next_action.json`) is a record check, not an experiment. Read the
authors' source data for Fig 4B (Ras activity, `msb201127-df4B.txt` in the open-access package)
and its legend. Find out whether a BRAF V600E line (HT29 or RKO) was measured with and without a
MEK inhibitor.

**Why this one:**
- In BRAF cells under MEKi, the stored windows give Ras-GTP **no_change for M1** and
  **inactive→active for M2** in all 32 cases. That is a change of category, so it needs neither
  RC1 nor RC2.
- The file is listed in `erk_pmek_measurement_v0/sources.json` as downloaded but unused. Its
  contents are unknown.

**Branches:**
- **Rise in a BRAF line:** revise toward a RAS-level feedback component (re-examine `M1_R_RAS`).
  This does not establish M2 as a whole.
- **No rise:** lower `M2_R_RAS` for these lines and keep M1. O1 stays held.
- **No usable BRAF contrast:** no conclusion, and D1 stands. The question becomes a proposal for
  a new Ras-GTP measurement. Dose, time and n are not fixed, because nothing supports them.

N1 was not performed. No data were requested and no one was contacted.

## 7. What this connection did, and did not, provide

**Did:**
- It turned a stored, host-aggregated "conditionally compatible" into a code-checked
  "partial/undecided", with the reason visible: the model values per case.
- It named the single table entry that M2's disagreement hangs on.
- It moved the next action from refining the pMEK readout to a check that separates the models
  without those two assumptions.

**Did not:**
- It does not show which site is right.
- It validates no model.
- It does not use any researcher's acceptance.

**Gaps found:** recorded as findings, not fixed.
- A text-stated direction ("pMek levels rise sharply") cannot enter a `change` comparison
  directly. A change is classified only from numbers under a `DecisionRule`, and categorical
  observations are limited to `state` claims. The host therefore had to declare a rule anchored
  on the authors' wording.
- `HostDecision` targets are checked only against a `ResearchReport` plan inside
  `compare_research_observations`. This case has no such plan, and none was invented. The test
  checks the targets against the case's own records instead.

## 8. Host use and counts

**Host:** one live call of `compare_model_observation` for M1 (`host_check.json`).
- Same outcome as the product path.
- Its `comparison_id` equals the local one when the input bytes are identical. A typed `1` vs
  `1.0` explains the one difference.
- The response shows r1-era fields. The exact deployed commit is not established.
- M2 was not sent.

**Counts:**
- `run_comparison.py`: 2 product calls, about 2 s, `run_logic_model` 0;
- 3 local cross-check calls;
- 1 host call;
- 0 literature searches or source reads.

Tokens and cost are not estimated.

## Files

| File | |
|---|---|
| `before.json` | question, D0, fixed inputs and triggers (committed first) |
| `run_comparison.py` → `comparison.json`, `run.json` | the comparison and its stamp |
| `decision.json` | layers A–D, review candidates, D1 |
| `next_action.json` | N1 and its branches |
| `host_check.json` | the live host call |
| `SHA256SUMS` | |
| Test | `tests/integration/test_observation_decision_update_v0.py` |
