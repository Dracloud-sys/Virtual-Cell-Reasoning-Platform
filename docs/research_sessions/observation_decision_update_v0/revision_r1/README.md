# Revision r1: CI cause, what was actually updated, and the next action's premises

The original records of this case are kept byte for byte (`../SHA256SUMS`). This revision corrects
how they describe their own scope; `corrections.json` holds the details. Nothing was re-run, and no
rule, threshold, table, model or product code was changed.

## 1. The CI failure

- **What failed.** Run 37794692374 tested the merge commit `6d2108d` (`1103343` into `06bf651`).
  The one failure was `test_model_observation_review_r1.py::test_the_review_results_rebuild`
  (case C8; C9 and C10 differ the same way).
- **Why.** CI installed pydantic 2.14.0; the records were made under 2.13.5.
  - A refusal relays pydantic's error text, which ends with a docs URL that carries the version:
    `errors.pydantic.dev/2.13/…` versus `/2.14/`.
  - `review_r1/results.json` stores that text verbatim.
- **Reproduced.** On a worktree at `6d2108d` with a fresh install (pydantic 2.14.0):
  - the test alone fails;
  - the full suite gives 1 failed, 2744 passed, 5 skipped, as CI did.
  - With the local pin (2.13.5), everything passes, which was the earlier local result.
- **Fixed in the test only.** The comparison ignores the version inside that URL and compares
  every other character. The records and their checksums are unchanged. The test passes under
  both versions.
- **Product code.** Unchanged. Refusal details relay the library's text; reported, not changed.

## 2. When D0 was judged

D0 is a reconstruction, not the latest recorded judgement. It joined two things:
- M1's "Base model" label from the pre-registration;
- the r0-style reading "M1 conditionally compatible, M2 disagrees".

It left out limits that were already recorded:
- **`logic_biology_v1` revision r1 §2:** M2's 불일치 needs the equal-category = equal-level
  assumption and is not a refutation of RAS-level feedback.
- **`logic_biology_v1` revision r1 §3:** M1's ordinal agreements are not promoted to a verified
  result.
- **`erk_pmek_measurement_v0` review r1 §4:** without that assumption, M2 says nothing about a
  rise within "active".

Against those limits, O1 was already not evidence that separates the sites.

## 3. New, reconfirmed, and not achieved

| | |
|---|---|
| **Reconfirmed, now tied to identifiers** | M1 gives no single direction (`mo-5526e1d7404ba90d`, partial/undecided). M2's disagreement rests on one table entry (`mo-a13253779baf2030`). Both link to stored run, model, observation and link hashes, and reproduce byte for byte. |
| **New** | A different next action: the Fig 4B source-data check (scope corrected in section 5). One live host call matching the product path. Two recorded gaps (a text direction needs a host rule; `HostDecision` targets need a plan). |
| **Compared** | KRAS pMEK only. **Ras-GTP was not compared**; it is a proposed action. A progress message called it "a cleaner discriminator"; that is corrected here. |
| **Not achieved** | A judgement changed by a new observation. No observation new to the case was compared, and D1's "hold" on O1 restates a recorded limit. This was a retrospective reproduction and linking of existing limits, plus one new proposed action. |

The tool returning a result is not the same as an observation changing the judgement. Here, only
the former happened.

## 4. What the ratio ≥ 3.0 rule is

**What it is.** A calculation assumption the host constructed for this case after the data were
known, so that `compare_model_observation` could be run. It is an example of the path running.

**What it is not:**
- a criterion from the paper: "three- to four-fold" (SW480) and "six-fold" (HCT116) are reported
  effect sizes;
- a validated assay or analysis criterion;
- new biological evidence.

**Mismatch, kept as recorded:**
- the rule cites SW480's wording;
- the comparison is HCT116, 50 µM against DMSO;
- values are relative to PBS;
- the authors' fold changes are not stated against DMSO.

**What follows:**
- That the tool needs a `DecisionRule` gives this rule no research justification.
- The outcomes in `../comparison.json` are results under this assumption, not findings about the
  data.
- The rule and the first run are kept unchanged. No other threshold was tried.

## 5. N1: what it can decide, and what it still assumes

**Kept:** the action, to read the Fig 4B source data (`msb201127-df4B.txt`) and its legend. It is
not performed.

**Withdrawn:**
- the claim that the Ras-GTP readout separates the sites without measurement assumptions;
- the three automatic branches in `../next_action.json`.

**Kept apart:**
- a quantitative Ras-GTP rise or fall;
- an analytical detection class;
- the Boolean active / inactive;
- a candidate model's overall adequacy;
- the biological site of feedback.

**Corrections:**
- M1's active → active does not forbid a measured rise.
- Comparing M2's inactive → active with data needs correspondences of category, intervention,
  time and sample level. None is established.

**Question first.** Does the file contain a valid BRAF-mutant treatment-vs-control comparison? If
it does, can only the quantitative direction be read from it, or can state categories be compared
under a stated basis?

**Branches:**
- **A category correspondence and the scope can be stated with a basis:** compare the candidates
  within that scope. Keep separating the candidates apart from deciding the feedback site.
- **Only quantitative values:** keep the observation. It refutes neither model's category
  prediction.
- **No valid comparison group, conditions, quality or data:** keep D1 and record exactly what is
  missing.

Whether the file answers the question is unknown, and nothing here promises that it will.

## Files

| File | |
|---|---|
| `corrections.json` | the CI cause, D0 timing, what is new and reconfirmed, the rule's standing, N1 r1 |
| `SHA256SUMS` | |
| Test fix | `tests/integration/test_model_observation_review_r1.py` |
| Revision test | `tests/integration/test_observation_decision_update_v0.py` |
