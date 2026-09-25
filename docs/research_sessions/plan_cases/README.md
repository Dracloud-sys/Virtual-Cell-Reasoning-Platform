# Stage A development cases: goal → hypotheses → experiments, with what code computes

Two unregistered research questions, run through the product path: `build_server()` → the
`research_evidence`, `read_evidence_source` and `check_research_draft` tools, with the real
Europe PMC provider. The drafts were written by the host (Claude Code), who also drove the tools
with a script. **This is not an MCP-connection test.** Connection was out of scope, so the tools
were called in-process on the same server a host connects to.

Files:
- `caseN_general_answer.md` — the host's ordinary answer from the same evidence, written
  **before** any plan analysis was run.
- `caseN_draft.json` — the host's plan: objectives, conditions, hypotheses, evidence roles,
  mechanism candidates, and predicted values per experiment.
- `caseN_draft_general_experiments.json` — the same plan restricted to the general answer's
  experiments, so the two can be compared on identical hypotheses and evidence.
- `*_result.json` — the ranges each read covered, and the full `check_research_draft` result.

Raw search dumps are not committed (they carry every hit's abstract excerpt); only the spans a
draft cites travel inside it.

**What is code and what is host.** Everything under "computed" below is the `plan_analysis`
output. Hypotheses, predictions, evidence roles and readings, mechanism candidates and the choice
of first experiment are the host's. The separations follow from the host's predicted values: a
wrong prediction gives a wrong separation. `scientific_validity_checked` was `false` in every run,
and an empty `findings` list would not have meant otherwise.

---

## Case 1 — ECM bridging scaffold (the original goal)

**Goal kept (A1).** Four user objectives: bridge and support (O1), cell ingress (O2), handover to
new ECM (O3), scar minimisation long-term (O4, in vitro proxy only). Confirmed: in vitro stage;
scarring is not a current endpoint. Open: material, cells, format, new-collagen method. Host
assumptions (type I collagen, dermal fibroblasts, EDC/NHS) are listed separately.

*Computed:* every objective reaches at least one experiment. **O2 is reached only by E2, and E2
separates no hypothesis pair** — it measures ingress for the goal but tells no alternatives apart.
That is a finding about the plan, not a defect.

**Hypotheses (coexisting unless marked).** Loss routes H1 proteolysis, H2 cell-independent, H3
contraction, H4 crosslinking trade-off, H5 persistent myofibroblast state; handover H6 retained new
collagen vs H7 secreted-not-retained; H8 reversal after withdrawal (marked exclusive with H5).

**Evidence (A2).** Server-read spans, all `server_retrieved` in the check.
- *Computed:* the handover method row cites three spans (`lit-670133a47aa6`, `lit-cd732cb414f8`,
  `lit-3011dae7c880`) — **one study**. H5 support: 4 spans, 3 studies (two spans are one sentence
  of the Dupuytren paper).
- The roles (method / scope_limit / supports) and readings are the host's.

**The pending decision, now read by the server.** "Measure new collagen in both construct and
medium" — Dupuytren Discussion `sec-10`, read in full (0–5996 and 5997–10827 of 10827,
`reached_end: true`). The passage (`lit-670133a47aa6` → `lit-eba9427a4c2d`):
- **supports** measuring both: after an overnight label and 3-hour chase, fully processed new
  collagen was mainly in the constructs and the medium held mainly proforms;
- **limits** it: the split is attributed to the chase time; the constructs were fibrin-based
  tendon-like constructs, not a porous collagen scaffold; the medium signal may include other
  collagens, so a medium readout needs a type-I-specific step and reads secretion, not deposition;
- **is insufficient** for telling new collagen from scaffold-derived fragments, which it does not
  address. Decision kept, with chase time as a design factor and a type-I-specific medium readout.

**Mechanism candidates (A3).** *Computed:* none of the six ECM links has an exactly matching entity
in the seeded graph (`endpoint_not_in_graph`) — the graph holds no ECM biology, and the links stay
case candidates. M3 (TGF-β1 → myofibroblast activation) has **no evidence and no conditions**; M6
(crosslink density → ingress) has **no evidence**; M4 (serum TGF-β → COL1A2) serves **no
hypothesis**. Nothing was written to the graph.

**Discrimination (A4).** *Computed:*
- **Pairs no candidate experiment separates:** H4 against H1, H2, H3, H5 — E1 has a crosslinking
  arm but the plan gives no prediction for H4 in it, so the arm separates nothing as written; H3
  against H8.
- **E4 without "gap length"** (the general answer's version): H3 (contraction) and H6 (handover)
  predict the same continuity result and are **not separated**; with gap length they are. That
  separation is by predicted values. It does **not** show handover: H6 says new collagen begins
  to carry load, and no readout in the plan measures that (see the revision below).
- Coexistence notes, e.g. E4: H1 (loss) and H6 (new ECM) predict opposite continuity effects and
  can both hold — an intermediate result could mean both, not neither.
- Coverage: E4's separated pairs strictly contain E3's.

**First experiment (host).** E3 (new vs original collagen, construct + medium, chase time as a
factor) together with E4 read **with gap length**: E4's continuity result is interpretable only
alongside E3's measure of retained new collagen and a gap-length readout, because continuity alone
cannot separate handover from contraction. Before running E1, either give H4 a prediction for the
crosslinking arm or drop the arm.

**Against the general answer.** Same first priority (new vs original ECM). What differed: the
general answer's bridge experiment had no gap-length readout (so could not separate handover from
contraction); its crosslinking arm stated no prediction; and it cited the construct/medium passage
without noting that its three spans are one study, or the chase-time and fibrin-construct limits.
What the analysis did not add: no new biology, and the choice of priority is the same.

---

## Case 2 — why did the resazurin signal fall? (a different unregistered question)

**Goal kept (A1).** User objective O1: decide whether the lower signal reflects cytotoxicity before
calling the compound cytotoxic. O2 (locate a metabolic change: content vs function) is marked
**host-added**. Open: compound class, exposure time, cell type.

**Hypotheses (all may coexist).** H1 fewer cells; H2a less mitochondrial content per cell; H2b lower
function per mitochondrion or other reductases; H3a direct chemistry with resazurin/resorufin; H3b
quenching/adsorption of resorufin.

**Evidence.** Server-read spans, all `server_retrieved`. Read in full: six abstracts; body sections
`s8-3` (resazurin, 2660/2660), `s7-5` (tetrazolium interference, 1210/1210) and `sec0008`
(cytotoxicity endpoints, 5716/5716).
- *Computed:* the H3b method row is two spans, one study; the H2b method row is two spans, one study.
- Decisive for design (host reading): `lit-d1719f786da7` — a cell-free resazurin + material
  incubation only shows the material does not chemically reduce resazurin; it does not rule out
  quenching or adsorption of resorufin; product controls (resorufin alone, resorufin + material) are
  needed. Source system: graphene materials — a scope limit for other compound classes.

**Mechanism candidates.** *Computed:* M3 PPARGC1A → Mitochondrial function **has a path in the
graph** (`PPARGC1A -promotes-> Mitochondrial function`) but **no case evidence**, and the path does
not carry the case's conditions. M4 (senescence → cell number) has no evidence and its target is
not in the graph. M1 and M2 carry evidence but are not in the graph.

**Discrimination.** *Computed:*
- **General answer's experiments** (cell-free resazurin, per-cell normalisation, ATP/membrane,
  mitochondrial content/OCR): **H3b is never separated from H2a or H2b.** A compound that quenches
  resorufin would read as lower metabolic activity per cell in every one of them.
  > **Withdrawn as stated (review, later the same day).** The second sentence is wrong: ATP,
  > membrane integrity, citrate synthase and OCR do not read resorufin. The first sentence came
  > from three defects in the matrix: no H3b prediction in E5, an ATP cell that generalised
  > graphene's luminometric interference, and H2 ATP cells the hypotheses do not fix. On the
  > corrected matrix, H3b **is** separated from H2a (E5 citrate synthase, under an assumption
  > about that assay) and **is not** separated from H2b. See `case2_matrix_review.md`.
- **Adding E2** (resorufin ± compound, no cells): no pair is left unseparated.
- E1 separates H3a from everything else, and nothing else.
- Coexistence: a per-cell decrease says H2 (or H3) holds; it cannot rule out H1 as well.

**First experiment (host).** One plate: E1 (resazurin ± compound, no cells) + **E2 (resorufin ±
compound, no cells)** + E3 (same-well cell count and resazurin per cell). Only if a per-cell
decrease survives both interference controls does E5 (mitochondrial content and OCR per content)
follow. The general answer chose E1 + E3.

**Against the general answer — stated plainly.** The passage that calls for the product control had
been read **before** the general answer was written, and the general answer still omitted it. The
analysis did not find the chemistry: it surfaced the gap because writing predictions made the host
split interference into H3a and H3b, and then the computation showed no experiment separated H3b.
A more careful ordinary answer could have caught it; this one did not.

---

## Defects the cases found in the analysis, and what was changed

1. **present vs absent was treated as opposing effects**, producing "may offset" notes for a
   cell-free control. `absent` is now a null like `no_change`. Test pinned.
2. **Hypotheses answering different sub-questions were compared**, filling case 1's "never
   separated" list with non-alternatives (e.g. a loss route vs handover). Now only hypotheses sharing
   a sub-question are compared. **This hid case 2's key result on the first rerun**, because the
   draft had put interference (Q1) and biological causes (Q2) under different sub-questions although
   both explain the same observation. The rule is now stated in the published schema, and case 2
   was restructured with Q0 "What causes the lower signal?" shared by all five hypotheses. Whether
   two hypotheses compete is the host's statement, not something code infers.

---

# Revision: prediction traces, corrected semantics, and B1

Everything below was run through the product path, as above: fresh `build_server()`, the same
searches and reads repeated so every cited id is `server_retrieved`, then `check_research_draft`
(with `what_if`) or `compare_research_observations`. The original drafts and results above are
kept unchanged.

| file | what |
|---|---|
| `case2_matrix_review.md` | every cell of the original case 2 matrix, kept / corrected / unconfirmed, with the reason |
| `caseN_structured_only.md` | condition 2: the same plan in structured form, written by hand **before** the revised draft was run |
| `caseN_revised_draft.json`, `caseN_revised_draft_result.json` | the corrected plan (references, bases, evidence, assumptions, readout specs, coverage) and its check, with `caseN_what_if.json` |
| `case2_revised_draft_general_experiments*.json` | the revised plan restricted to the general answer's experiments |
| `case2_b1_rules.json` | mappings and decision rules, **committed (d7d8bc2) before any observation was written** |
| `case2_b1_observations.json` | four synthetic scenarios as `ExperimentRun` records |
| `case2_b1_reading_without_vcrp.md` | conditions 1 and 2 for the observations, written before the comparison ran |
| `case2_b1_decisions.json`, `case2_b1_S*_result.json` | the host's keep/revise/hold, and each scenario's comparison |

**Every number in the B1 files is synthetic.** The rules' bounds are the host's, invented to
exercise the comparison. None of them is a literature or instrument value.

## Case 1: evidence → prediction

*Computed:*
- **Objectives.** O3 (handover) and O4 (scar) are **reached by no experiment directly**. O3 is
  reached through proxies only (E1, E3, E4) and O4 through a proxy only (E5). O1 is reached
  directly by E4 and O2 by E2. The levels are the host's judgement, and code only collects them.
- **Traces.**
  - E3's H6 prediction rests on `lit-670133a47aa6` (method) plus a stated assumption about chase
    length and type-I specificity.
  - E5's H5 uptake prediction rests on M1, whose one span is from lung myofibroblasts.
  - **Eleven predictions** say their basis is `assumption` and state none. The hand-written
    structured answer did not notice a single one.
- **Pairs.** 14 pairs were not compared, each listed (no shared sub-question, not declared
  alternatives). Never separated: H4 against H1, H2, H3 and H5; H5 against H1, H2 and H3; and H3
  against H8.
- **E1 corrected.** "Loss reduction by inhibitor" was a change written as a state, and it is now
  a change vs vehicle. E1 no longer claims H5: H5's degradation claim is relative to
  non-activated cells, an arm E1 does not have. The crosslinking arm now carries an H4
  prediction, but it still separates nothing, because crosslinking may slow proteolysis and
  hydrolysis too. It is kept as a function check.
- **What if.**
  - Withdrawing `lit-670133a47aa6` affects E3/H6 and M4.
  - The same-study span `lit-eba9427a4c2d` stays in force. `what_if` withdraws spans, not
    studies (finding 4 in `docs/research_path.md`).
  - Changing the E5 condition string, or M1's condition, affects every E5 prediction. For H5
    uptake the change travels through M1 as well. Condition matching is exact text.

## Case 2: evidence → prediction, and the corrected finding

*Computed on the revised draft:*
- E2 separates H3b from H1, H2a and H2b.
- E3 separates H1 from the rest.
- E5 content separates H2a from H1, H2b, H3a and H3b.
- **E4 now separates nothing.** Its ATP cells for H2 became `not_predicted`, because glycolysis
  may compensate. It stays in the plan as a function check (O1 direct).
- E6, the cell-free luciferase check that the ATP cells' assumption needs, separates nothing by
  design.
- Never separated: H2b vs H3a, and H3a vs H3b.
- Restricted to the general answer's experiments, H2b vs H3b is never separated either.

**Withdrawing the graphene product-control span** (`lit-fd67cab1bedc`) affects H3b's
predictions in E2 and E3 and link M1. No value changes.

## B1: observation-driven keep / revise / hold (case 2, synthetic)

| | what the comparison computed | host's proposal |
|---|---|---|
| **S1** interference-consistent | E2 decrease on all 9 pairings (0.51–0.58): H3b consistent. H1, H2a and H2b read **inconsistent**, meaning "alone they predict no cell-free change". Cell number unchanged: H1 inconsistent. Per-cell decrease. | keep H3b; revise the per-cell resazurin readout (unusable for this compound); revise H1; **hold** H2a/H2b (coexistence), next E6 → E4 → E5 |
| **S2** needs more measures | E2 no change: H3b inconsistent. Per-cell decrease. ATP unchanged: H1, H3a and H3b consistent, H2 not read (not predicted). **E6 could not be read** (`unknown_readout`). | revise H3b and H1; hold H2a/H2b, next E5; hold the luciferase assumption, which rests on a hand reading |
| **S3** insufficient | E2 `replicates_disagree` (0.60–0.99). Per-cell 0.85: between bands, all undecided. | hold everything; repeat E2 and E3. No replicate rule invented |
| **S4** not comparable | E2 `unit_mismatch` (AU vs RFU). E3 `no_observations_at_time_point` (vehicle at 48 h). E4 `all_treatment_readings_left_out` (2 suspect, 1 bound). E5 `assay_mismatch` ("absorbance" vs "DTNB absorbance"). | hold E2–E5 and fix the records |

In every scenario the plan's hash was unchanged, and each run is its own revision.

**Code vs host.** Code computed comparability, the classifications under the declared rules,
the per-prediction outcomes and the dependencies to re-examine. The host wrote the rules, the
mappings and every keep/revise/hold, and read E6 by hand. The biggest judgement the code could
not make was S1's H2 "inconsistent": the host held H2 because it can coexist with H3b.

## The three conditions, compared

| | general answer (1) | structured, by hand (2) | VCRP analysis + update (3) |
|---|---|---|---|
| case 2 H3b vs H2 | stated no product control at all | H3b vs H2a only under an assumption; H3b vs H2b not separated | same as (2), computed; also H2b vs H3a never separated, which (2) did not state |
| case 1 bases | none | wrote bases, but 11 carried no assumption | flagged all 11 |
| case 1 pairs | none listed | three groups of unseparated pairs | 8 never separated, plus 14 excluded pairs, each with its reason |
| what if | none | noted M1 and M4 | named every affected prediction, link and experiment; exposed span-vs-study |
| S4 (bad records) | **built a biological story from unusable data** | caught all four issues, with the rule file open | caught all four issues, including the assay string (2) would have accepted |
| S1 H2 | "quenching; check biology orthogonally" | marked ✗ without saying it isn't evidence against H2 | marked inconsistent; the limit and the host's hold carry the caveat |

**What could not be matched, or would not be fair.**
- (2) was written by a host who had already seen stage A's output, so it is not an independent
  condition.
- No reader outside the host has judged any of the three.
- Counts of flagged items are not a quality score, and no holdout claim is made.
- The B1 scenarios were designed by the same host who wrote the rules, so they test that the
  comparison does what it says, not that it helps with real data.

## Not done

- File input, saving and resuming a session, statistics, and unit conversion.
- A place in the plan for an experiment that checks an assumption (finding 2).
- Study-level withdrawal (finding 4).
- Independent evaluation of design or update quality.

These cases are cases, not an evaluation.
