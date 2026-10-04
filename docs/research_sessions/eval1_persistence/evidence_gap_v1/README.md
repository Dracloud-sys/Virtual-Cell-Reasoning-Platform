# Evidence gap v1: one gap in the eval1 plan, read and carried into the plan

**Date** 2026-10-04. **Base** `a1dfca9` (PR #35 merged into main). **Host** Claude Code, with
the local stdio `virtualcell` server from `.mcp.json` running this repository's `src/` at
`a1dfca9` (started before any change here, so it has no `revision` field).

Same model as before, same session as the analysis. **Not an evaluation and not a holdout.**
The cells, dose, duration and phenotype are the eval1 development assumptions, never confirmed by
a researcher. Nothing below is an observation of an experiment.

## 1. The gap chosen, and why it decides something

The original plan (`../records/condition_B_payload_2.json`, sha256 `dda23951…`, unchanged; listed
in `../records/SHA256SUMS`) records under *What is NOT in the pack*:

> No primary source read here measures residual exogenous TGF-β1 after washout … Statements about
> residual ligand rest on general knowledge.

Chosen question (host's choice): **after washout, what tells carried-over recombinant TGF-β1
apart from TGF-β1 the cells make?**

Why this one (host's judgement, not computed): E1 is the plan's first experiment, and how every
later result is read depends on it.
- Its branches 1–3 split H1 (carryover) from H2/H3 (cell- or matrix-derived ligand).
- Its blockade arms b/c predict `decrease` for H1, H2 and H3 alike.
- ML11 is the plan's only mechanism link with `no_evidence`.

If the answer differed, the readouts of E1 and the reading of a blockade null would differ. The
other recorded gap (no source on paracrine transfer) feeds E2, which only runs after E1.

What the four kinds of "unknown" were before reading:

| | |
|---|---|
| observed absence | none: nobody measured carryover in this system |
| record unchecked | the lot's form (with or without LAP), serum level, plastic: open conditions |
| evidence not retrieved | residual ligand after washout; how autocrine and carried-over ligand differ |
| analysis assumption | "cells neither consume nor add ligand"; "blockers fully block" |
| measurement uncertainty | ELISA floor for carried-over ligand (an assumption check in E1) |

## 2. Searches and reading

Four `research_evidence` calls with `search_literature: true`. The search used the question
text only: no species, cell or condition filter was applied, and none is claimed.

| # | Purpose | Query | Result |
|---|---|---|---|
| 1 | direct observation | `recombinant TGF-beta1 retained after washout adsorbed to culture surface or extracellular matrix residual activity fibroblasts` | 18 found, 1 with text: a PET commentary, irrelevant. Long AND-ed queries return almost nothing. |
| 2 | method: source of ligand | `TGF-beta1 autoinduction fibroblasts` | 25 with text. Picked: Webber 2009 (pulse-washout, maintenance) and Zhang 2006 (autoinduction method). |
| 3 | opposite results / non-reversal | `myofibroblast reversal after TGF-beta1 withdrawal` | 12 with text. Picked: Sci Rep 2023 (human cardiac fibroblasts, blockade does not reverse). |
| 4 | method: latent vs active form | `latent TGF-beta1 secreted by fibroblasts measured acid activation versus active TGF-beta1` | 24 with text, none on telling carried-over from secreted ligand by form. |

Searching "reversal" (search 3) was not a review of opposing evidence: one search found one
non-reversal study.

Reading (`read_evidence_source`, 9 calls; plus 1 PubMed full-text call):

| Source | Read | Not read |
|---|---|---|
| **W** Webber et al., JBC 2009, doi 10.1074/jbc.M806989200 | whole abstract (`lit-e60fafae0030`, `lit-0650a4586f10`) | full text: `not_available` from this server, and the PubMed tool returned an empty body. Methods, figures, cell source, washout: **unread** |
| **Z** Zhang et al., Am J Pathol 2006, doi 10.2353/ajpath.2006.050921 | whole abstract (`lit-fcd84996ed09`, `lit-bc7c597aaca4`) | full text `not_available` |
| **S** Sci Rep 2023, doi 10.1038/s41598-023-39369-y | sections *In vitro treatments*, *Long-term culture…*, *Chronically activated human fibroblasts cannot transition back…*, each to the end (7 spans) | abstract tail, other sections, all figures, tables and supplementary material |

Three papers, ten spans. The revision counts them as **3 studies, 10 spans**.

On the live host, all ten spans came back `server_retrieved` (issued by this server and
unchanged). The host's own prior came back `host_supplied`. The 17 original spans are
`host_supplied` now, because this server process did not issue them.

## 3. What the sources say, where, and what is still assumed

**W, abstract only.**
- *What the source states:* fibroblasts given TGF-β1 10 ng/mL for 72 h kept the phenotype for up
  to 120 h after removal. pSmad2/3 phosphorylation persisted, and persistence was inhibited by
  anti-TGF-β1 antibody and SB431542. HA synthesis and HAS2 were needed for α-SMA. 4-MU and HAS2
  siRNA did not change Smad phosphorylation.
- *The authors' reading:* the persistence was "because of autocrine synthesis", and HA mediates
  it.
- *Host's reading:*
  - **direct support for H2**, at abstract level;
  - **contradicts H4** in a pulse system;
  - **limits H1's tests:** antibody and receptor blockade cannot tell carried-over from new
    ligand.
- *Unread:* species, tissue, washout procedure, how carryover was excluded, how synthesis was
  measured, and when blockade started.

**Z, abstract only, proximal tubular epithelial cells.**
- *What the source states:* added TGF-β1 raised TGF-β1 mRNA and de novo protein, through Smad3
  and ERK for mRNA and p38 for translation.
- *Host's reading:*
  - **method:** if this also holds in fibroblasts, ongoing signalling raises TGFB1 mRNA whatever
    the ligand's source, so mRNA cannot mark the source;
  - mRNA can also miss a change made at translation.
- *Scope limit:* epithelial cells.

**S, results sections.**
- *What the source states:* human cardiac fibroblasts from explanted diseased hearts, after up
  to 10 passages on 3 GPa plastic, were about 70% α-SMA-positive with no added TGF-β. Neither
  SD208 (30 nM), SB431542 (10 µM, p5–p9), nor 25 or 2 kPa substrates lowered α-SMA, alone or
  combined, and the cells did not respond to TGF-β.
- *Host's reading:*
  - **scope limit on H4:** a state no ligand pulse established also fails to reverse under
    blockade, so a blockade null does not pick H4;
  - **method for H5:** the plastic baseline can be high.
- *Not applicable as is:* no pulse, diseased cells, long passaging.

**Conflict kept, not resolved.** Does receptor blockade reverse a TGF-β1-induced persistent
state?
- S1 (rat cardiac, SD-208): no.
- W (fibroblasts, antibody/SB431542, timing unread): persistence inhibited.
- S (human cardiac, chronically activated, not a pulse): no.

The systems differ in species, inducer and duration, and the timing in W is unread.

**Still assumed, and new:**
- the recombinant lot carries no LAP (so latent ligand or LAP in the medium is cell-made);
- newly secreted TGF-β1 leaves these cells mostly latent.

Both are host knowledge, entered as a `model_prior` (`prior-latent-vs-active`, a search target)
and as an assumption check. Search 4 did not find a source for either.

**Still unknown (the gap itself):** whether recombinant TGF-β1 stays on plastic, ECM or cells
after washout, and for how long. No source was found, and ML11 still carries no evidence.

## 4. The plan before and after

`build_revised.py` makes the revision from the original and changes only what is below. The
code reports E2–E6 unchanged, along with 6 of 8 hypotheses, 12 of 12 earlier links and 142 of
144 predictions.

| | Before | After | Host decision |
|---|---|---|---|
| H1 carryover | unverified; ML11 no evidence | same | **unchanged_no_new_evidence** |
| H2 autocrine | 3 studies, by analogy (ILD, CAF, senescence) | + W as direct support; ML13 (W), ML15 HA (W) | **keep** |
| H4 intrinsic state | supported by S1; its E1 arm-c `no_change` read off S1 | + W contradicts, S limits scope. Values unchanged. Arm-c prediction gains an `unresolved` on the source conflict | **hold** |
| H5 mechanical | — | S added as scope limit and method only | **keep** |
| E1 readouts | active TGF-β1, pSmad2 d3, α-SMA | + `latent_TGFb1_in_CM` (acid-activated minus native, + LAP), with LAP-free assumption check on dosing medium and arm f; + `TGFB1_mRNA_cells`; + pSmad2 d5 vs d1 | **revise** |
| E1 predictions | 144 | 152: mRNA `increase` for H1, H2 and H3 alike (stated as not a source marker); latent: H1 `no_change`, H2 `increase` vs arm f (assumption); pSmad2 d5 vs d1: H1 `decrease` (assumption), H2 `no_change` (W) | (E1 revise) |
| E1 branch 2 | "cell-free at floor, cells' medium above never-treated → H2/H3, H1 drops" | only a latent/LAP rise over arm f says *newly secreted*, and only if the dosing medium has none. Active-only excess does not split H2 from H3 | (E1 revise) |
| E1 branch 3 | "blockade null → no ligand route necessary; H4–H7 lead; would mirror the rat result" | "no ligand route necessary *from when blockade began*; does not show the state never needed ligand and does not pick H4; E3–E5 decide" | (E1 revise) |
| E1 branches 4, 5 (new) | — | pSmad2 sustained d1→d5 with cell-free at floor → re-supplied, read with latent; pSmad2 falls while α-SMA persists → not H4 alone (HA, H5, H7) | (E1 revise) |
| Priority | E1 first | E1 first, reason extended | (E1 revise) |
| Assumptions | 10 | + search done, none found; + LAP-free lot | — |

No predicted value moved (`value_changes: []`). No change is untraced, and none lacks a decision.
The revision has no findings.

### What the code confirmed, and what it did not

**Computed by code from the two drafts** (`revision_with_decisions.json`, product path):
- what changed and what did not;
- that every change cites a new id or sits under a decision;
- the ten spans counted as three studies;
- which predictions cite each new id;
- what rests on the new ids (`what_if`: H1–H5, ML13–15, E1, 7 predictions);
- that no value moved;
- that each decision matches what changed.

**The host's, not checked by anything:**
- every role and reading;
- which gap mattered;
- that W supports H2;
- that blockade cannot tell the sources apart;
- that the LAP route would work;
- the conflict reading;
- the branch rewrites.

**Not changed by the revision, computed on the live host:**
- E1's separated hypothesis pairs are the same 21 before and after. H2/H3 is still not
  separated by E1.
- The revision did not add a computed separation. What it changed is which readout carries
  H1-vs-H2 (one with a testable assumption, rather than blockade, which carries no source
  information), and how a blockade null may be read.

## 5. Was it useful? Concrete differences, and their limits

**What changed in the plan:**
- **A core assumption now has a source behind it, in part.**
  - E1's H1-vs-H2 split rested on cell-free wells plus "cells neither consume nor add ligand".
  - It now also has a readout with its own check (latent/LAP against the dosing medium).
  - W gives a precedent for the autocrine reading, not for carryover.
- **One wrong inference was avoided.**
  - Without Z, TGFB1 mRNA is a natural "is the cell making ligand?" readout.
  - With Z, the plan says outright that it rises under H1, H2 and H3 alike.
- **An opposing result and a scope limit are now in the plan.**
  - Branch 3 no longer reads a blockade null as H4 "mirroring the rat result".
  - W's opposite result and S's chronically activated non-reversal stop that reading.
- **The measurement and its interpretation are more specific:**
  - a dosing-medium LAP control;
  - a pSmad2 time course;
  - a note that pSmad2 and α-SMA can come apart (ML15).
- **Unchanged:** E1 is still first, E2–E6 are untouched, no predicted value moved, and ML11 still
  has no evidence.

**Where each effect came from:**
- *From the new sources (the reading):* the autoinduction caution and the conflicting blockade
  results.
- *From VCRP (the tracing):* showing that nothing else moved; that the change is confined to E1,
  H2 and H4; that ten spans are three studies; that the computed separations did not change, so
  the plan's discriminating power was not inflated; and the pinned finding below.
- *Not shown:* that this is better than a general answer given the same papers. This case does
  not test that.

## 6. Next actions

These are the host's proposal; the researcher decides.

**Records to check first** (they decide how E1 reads):
1. the recombinant TGF-β1 lot's datasheet (with or without LAP, and the carrier);
2. the serum percentage during and after washout;
3. W's methods, if the article can be obtained another way.

**Then experiments:** E1 as revised. The dosing-medium LAP check and arm f are what make the
latent readout interpretable. They are needed before *interpreting* E1. Collecting the other
E1 data does not have to wait for them.

## Finding recorded, not fixed

**Pair analysis keeps one prediction per hypothesis and readout.**
- What happens: `plan._discriminate` stores `table[hypothesis][readout] = expected`. So when a
  readout has predictions under several conditions or references, only the last one is
  compared.
- The original E1 already had two conditions per readout (arms b and c; arm f and arm a), so its
  computed separations used only the last-listed prediction of each.
- In the revision, the new pSmad2 d5-vs-d1 predictions displaced the d3-vs-never-treated ones for
  H1 and H2. That produced 10 `different_reference` exclusions on pSmad2 (seen on the live host as
  `readout_exclusions: 10`), though the separated pairs happened not to change.
- Pinned by `test_finding_pair_analysis_keeps_one_prediction_per_readout`; not fixed in this
  milestone. The revision comparison itself keys predictions by condition and reference and is
  not affected.

## Files and checksums (`SHA256SUMS`)

| File | What |
|---|---|
| `benchmark_questions.md` | R1–R10, written before `research/revision.py` |
| `new_evidence.json` | the 10 spans as issued (hash-validated) + the host prior |
| `build_revised.py` | original → revised draft and decisions, deterministic |
| `draft_revised.json`, `decisions.json` | the revision and the host's decisions |
| `host_calls.md` | the two live-host `check_research_draft_file` calls, key fields transcribed |
| `run_revision.py`, `run.json` | the product-path run and its input/output hashes |
| `revision_file_route.json`, `revision_with_decisions.json` | product-path results (compact) |

## Counts

| | |
|---|---|
| `research_evidence` | 4 (the limit) |
| `read_evidence_source` | 9 (3 abstracts, 2 full-text `not_available`, 1 section list, 3 sections) |
| PubMed full text | 1 (empty body) |
| `check_research_draft_file`, live host | 2 (original, revised), both compact |
| product-path revision calls | 2 (`run_revision.py`) |
| papers read | 3 (limit 3) |

Tokens for this session are not reported by the harness at the granularity of this case, so none
are given. Measured as compact JSON, the `revision` object is 13 KB (file route) and 15 KB
(with decisions). The rest of each reply, the compact draft check, is about 23 KB. The stored
files are indented, so they are larger.
