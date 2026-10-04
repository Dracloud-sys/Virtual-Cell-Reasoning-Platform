# Revision 2: condition-aware pair analysis, and readings narrowed to what was read

**Date** 2026-10-04. **Review base** `28c4933`.

Revision 1 (`../draft_revised.json`, sha256 `663eaf84…`), its decisions, its comparison outputs
and the original plan are **not rewritten**. Neither is `../README.md` below its correction note.
This directory adds a second revision built from revision 1 (`build_r2.py`, deterministic),
the comparisons, and the pair analysis computed before and after the code fix.

No search was run and no new source was read. Every correction is checked against spans that
were already in the draft.

## 1. Pair analysis now keeps every condition

**Before** (up to `28c4933`, recorded as a pinned finding in `25c3af3`):
- `plan._discriminate` kept one prediction per hypothesis and readout. Of several conditions,
  only the last-listed was compared.
- A second prediction against another reference could displace a comparable one. This produced
  revision 1's 10 `different_reference` exclusions.

**Now:**
- Predictions are compared within a **slot**: a readout under a condition, both as written. The
  condition is where these plans put the arm and the time point.
- Inside a slot, each reference (`versus`) is kept. Only predictions of the same kind against
  the same reference are compared; a change with no stated reference is compared as before.
- A pair that shares a readout but no condition gets a `different_condition` exclusion, and its
  conditions are listed.
- Two values from one hypothesis for the same readout, condition and reference give a
  `conflicting_predictions` finding. Neither value is compared, whatever the order.
- Slots are iterated sorted, so reordering predictions does not change the result.
- Separations, exclusions and outcome rows carry the condition. Prediction traces credit a
  separation only on the prediction's own condition.
- Nothing matches synonyms or parses time points; conditions match as written.

**Recomputed** (`pair_analysis.py`; `pairs_28c4933.json` from a checkout of `28c4933`,
`pairs_fixed.json` from this code):

| Draft | Experiment | Separated pairs | Readout×condition entries carrying them | Exclusions | Outcome rows |
|---|---|---|---|---|---|
| original | E1 | 21 → 21 (same set) | 42 → 64 | 0 → 0 | 3 → 5 |
| original | E2 | 21 → 21 (same set) | 36 → 48 | 0 → 0 | 3 → 4 |
| original | E3–E6 | unchanged | unchanged | 0 → 0 | unchanged |
| revision 1 | E1 | 21 → 21 (same set) | 39 → 69 | **10 → 0** | 5 → 8 |
| revision 2 | E1 | 21 → 21 (same set) | 38 → 68 | **5 → 0** | 5 → 8 |

The unseparated pairs and their reasons are identical everywhere.

What changed is what carries each separation. In E1 of the original, before the fix H1|H4 was
credited to α-SMA (the arm-b prediction, listed last) and pSmad2. It is now also carried by
α-SMA under arm c and by active ligand in arm f.

No pair moved between separated and unseparated. That was not a target, and it is recorded as
it came out.

## 2. Readings corrected (revision 1 → revision 2)

| Question | What the span says | Revision 1 said | Revision 2 |
|---|---|---|---|
| 1. pSmad2 over time (`lit-e60fafae0030`) | "persistent phosphorylation despite removal", no time points | H2: pSmad2 d5 vs d1 `no_change`, basis `evidence_observed` | **`not_predicted`**. The persistence observation goes into a note. Under H2 the d1–d5 level depends on autocrine output against decay, and nothing read gives either. Branch 4 (pSmad2 sustained) is now read as consistent with re-supply, uncleared carryover or slow turnover, and not as evidence for H2 on its own. |
| 2. LAP / latent form | (host prior; no source) | a LAP-free lot means latent ligand "was made by the cells"; latent readout as the source marker | The dose assumption now says only "did not come from the dose itself". A separate, **untested** assumption covers cell secretion after washout versus release of material held from the pulse. H2 keeps the assumption that secreted TGF-β1 is mostly latent, with a note that this is a candidate measurement, not a validated way to tell the source. **H3 added as `not_predicted`**: the cell-free arm has no deposited matrix, so release from it (the plan's ML8) is uncontrolled. Branch 2 no longer lets a latent rise separate H2 from H3, or show timing, activation or function. The prior `prior-latent-vs-active` is replaced by `prior-latent-form-r2`, which states those limits. |
| 3. HA and Smad (`lit-0650a4586f10`) | 4-MU / HAS2 siRNA lowered α-SMA with Smad2/3 phosphorylation unchanged; HAS2 siRNA "prevented phenotypic activation" | ML15: HA required for α-SMA after removal, "independently of Smad phosphorylation"; branch 5: "the HA coat was reported to hold α-SMA independently of Smad phosphorylation" | ML15 now reads "required with Smad2/3 phosphorylation unchanged". Its target is "α-SMA expression"; conditions say it is **not** shown that HA holds α-SMA without pSmad, and not stated whether this was during induction or after removal. Branch 5: nothing read shows what holds α-SMA without pSmad2; ML15 is not evidence there. |
| 4. Sci Rep 2023 (`lit-436033cdfec3`, `lit-1ba98dbcd8f3`, `lit-758a014077fb`, `lit-8ad9688ecbdd`) | cells from explanted diseased hearts, ≤10 passages on 3 GPa plastic, no TGF-β added by the authors | "a state no ligand established"; "before any TGF-beta" | No TGF-β1 pulse was **added**. Whether endogenous or medium TGF-β took part is unknown. The difference is origin, induction and culture history; the source shows a blockade null can occur without picking H4, not that ligand was absent. Same change in the H4 arm-c `unresolved` text and branch 3. |
| 5. TGFB1 mRNA | (autoinduction, epithelial cells) | "this readout does not tell them apart" | Alone it does not tell where extracellular ligand comes from or whether it acts. It still reads continuing signalling-driven transcription (H1–H3 against H8). A flat value weighs against transcription-driven autocrine supply, though translation can change without it (`lit-bc7c597aaca4`). |

Revision 1's priority rationale said E1 "now measures the latent form". It now says E1 adds a
latent-form readout **as a candidate**.

## 3. What the comparison reports (`revision_r1_to_r2.json`, `prediction_changes.json`)

**Revision 1 → revision 2:**
- **Predicted values changed:** 1 (H2 pSmad2 d5 vs d1: `no_change` → `not_predicted`).
- **Predictions added:** 1 (H3 latent vs arm f, `not_predicted`).
- **Predictions removed:** 0.
- **Changed in other fields only:** 6.
  - H4 arm-c `unresolved`;
  - the three mRNA notes;
  - H1 latent `assumptions`/`evidence_ids`;
  - H2 latent `assumptions`/`evidence_ids`/`note`/`unresolved`.
- **Other objects changed:**
  - ML15: relation, target, conditions;
  - E1: assumption check, branches, priority rationale;
  - five evidence-link readings;
  - one plan assumption replaced;
  - the host prior replaced (one evidence id removed, one added).
- **Findings:** three `prediction_assumption_removed`. These are the replaced LAP sentence on H1
  and H2, and the dropped "pSmad2/3 holds over day 1 to 5" on the value that became
  `not_predicted`. Each is intended and reported, not hidden. A first build of revision 2 also
  dropped "secreted TGF-β1 is mostly latent" from H2. The same check flagged it, and it was
  restored because the prediction still rests on it.
- **Nothing untraced and nothing undecided.** E2–E6 are unchanged.

**Original → revision 2** (`revision_original_to_r2.json`, no decisions sent):
- 0 values changed, 9 added, 0 removed, 2 changed in other fields only.
- Six changes are listed as untraced because no decisions were sent with that comparison.

`value_changes: []` in revision 1's record meant that no **existing** value moved. It did not
mean the predictions were unchanged: revision 1 added 8.

A change that is tied to a new evidence id or to a decision is **traceable**. That does not
make it scientifically justified, and nothing here checks that.

## 4. The research gap is still open

Carried-over versus cell-made TGF-β1 after washout is **not resolved**:
- no source measuring residual exogenous ligand was found;
- ML11 still has no evidence;
- the latent/LAP readout is a candidate whose interpretation rests on untested assumptions.

Adding it does not resolve the gap. What the case leaves behind is a narrower plan, its
assumptions written down, and two record checks to run before E1 is interpreted: the lot
datasheet and the serum level.

## Files

| File | What |
|---|---|
| `build_r2.py` | revision 1 → revision 2, each edit commented with its span and question |
| `draft_revised_r2.json`, `decisions_r2.json` | revision 2 and the host's decisions |
| `run_r2.py`, `run_r2.json` | product-path comparisons and their hashes |
| `revision_r1_to_r2.json` | file route plus with-decisions route |
| `revision_original_to_r2.json` | revision 2 against the original |
| `prediction_changes.json` | predictions split into value changed / added / removed / other fields |
| `pair_analysis.py`, `pairs_28c4933.json`, `pairs_fixed.json` | every experiment's pair analysis for all three drafts, before and after the fix |

Revision 1's stored compact replies (`../revision_*.json`) include a pair summary computed at
`25c3af3`, before the fix. They are kept as recorded, and their `revision` objects still replay
unchanged.

**Not done:**
- **live-host run:** the connected server still runs `a1dfca9`, which has neither `revision` nor
  the fix;
- **Webber methods:** the full text was not obtained.
