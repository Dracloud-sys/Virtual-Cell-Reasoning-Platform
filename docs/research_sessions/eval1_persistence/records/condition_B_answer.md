# Telling apart why a phenotype persists after the treatment stops

**Marking convention.** Statements marked **[VCRP]** are computed output of the research-plan checker
(`check_research_draft`, two calls, results in `condition_B_check_1.json` / `condition_B_check_2.json`).
Everything else is my own judgement. The checker reports in its own words that it does **not** check
scientific plausibility, whether the alternatives really compete, whether an experiment would separate
anything, or whether a source supports what it is cited for **[VCRP: `not_checked`]**. All 17 evidence
spans I submitted came back as `server_retrieved` — issued by the server and unchanged **[VCRP]**.

---

## 1. The goal, restated without narrowing it

After a 48-72 h pulse of TGF-β1 (2-5 ng/mL) on primary human fibroblasts and a washout into
TGF-β1-free medium, α-SMA stress fibres and contractility are still there days later. The question is
which of the possible maintainers is doing the work. I am **not** assuming it is one of the three named
in the question, and I am **not** assuming they exclude each other. Six goals drive the plan:

- **O1** does maintenance require ongoing TGF-β receptor input at all;
- **O2** if so, where does the ligand come from (carryover / matrix latent pool / cell-secreted);
- **O3** which cell-intrinsic route is at work (chromatin-TF memory, senescence, mechanical self-reinforcement);
- **O4** is this a per-cell change or a change in who is in the dish;
- **O5** do the readouts measure what they are taken to measure;
- **O6** what reverses it, and on what timescale.

These objectives are **mine, not the researcher's** — nobody stated goals, so they are submitted as
`stated_by: host`. The cells, dose, duration and phenotype are fixed development assumptions, not
user-confirmed facts, and they are recorded as assumptions in the plan.

## 2. The alternative explanations, and how they relate

| | Explanation | Coexistence / exclusivity |
|---|---|---|
| H1 | Residual exogenous TGF-β1 (medium carryover, or adsorbed to plastic, deposited ECM, serum protein, cell surface) still signalling | can coexist with all others |
| H2 | Cell-secreted factors — autocrine TGF-β1 or another mediator, including a senescence secretome — acting on self and neighbours (the question's "cell-to-cell signalling") | coexists; overlaps H6 by construction |
| H3 | Latent TGF-β in the cell-deposited matrix activated locally, with no new exogenous ligand | coexists; mechanistically adjacent to H1 and H2 |
| H4 | A cell-intrinsic stable state (chromatin accessibility + TF circuit) needing no receptor input | coexists |
| H5 | Mechanical self-reinforcement: stiff plastic + already-built stress fibres keep tension, tension keeps α-SMA | coexists |
| H6 | Senescence: a stable arrest with its own secretome, not a reversible differentiation state | coexists |
| H7 | Population composition: the pulse enriched an α-SMA-competent, near-non-proliferating subset; no cell holds a memory | coexists |
| H8 | No persisting state at all: slow α-SMA protein turnover + cohort/confluence drift — the measurement, not the biology | **the only exclusivity in the plan**: stated in the strong form, so it excludes H1-H7 |

Marking only H8 as mutually exclusive is deliberate: coexistence is the default, and a plan that marks
competitors as exclusive would force a single winner that the biology does not require. The checker
compared all 28 pairs, every one by `shared_sub_question` **[VCRP: `pair_selection`]**.

## 3. Mechanism kept separate from measured signal

The mechanism claims are recorded as twelve case-level links (ML1-ML12) with their own conditions —
rat cardiac fibroblasts, valvular interstitial cells in fibrin, CAFs on stiff ECM, MSCs primed by
stiffness, Dupuytren palmar fibroblasts, ILD patient fibroblasts. The readouts are separate objects
with assay, compartment, unit, normalisation and reference. Nothing in the plan says "α-SMA stress
fibres = myofibroblast state"; α-SMA-in-fibres is a stain, contraction is a force, pSmad2 is a
phosphorylation, ATAC signal is accessibility, and each hypothesis is a claim about what maintains the
cell, not about the stain. **[VCRP]** reports every mechanism link as `case_candidate`, and all twelve
as `not_in_graph` — the curated knowledge graph holds no route between these exact entity names, so
none of the mechanisms is corroborated by the platform's graph. One link, **ML11** (exogenous TGF-β1
adsorbing and desorbing after washout), is flagged `no_evidence` **[VCRP]**. That flag is correct and
intended: no source in this pack measures residual exogenous ligand, so the whole residual-ligand leg
rests on general knowledge. That is exactly why it is the thing E1 measures first.

## 4. The experiments: what each one expects, separates, and cannot separate

Predicted values are given per hypothesis per readout in the submitted plan; below are the decisive ones.

### E1 (priority) — washout quality, ligand measurement, blockade timing

Arms from the moment of washout: (a) vehicle; (b) pan-TGF-β antibody 1D11 10 µg/mL + isotype;
(c) SB431542 10 µM continuous + DMSO; (d) SB431542 delayed to day 3; (e) never-treated; (f) **cell-free
wells pulsed and washed identically**; (g) acute TGF-β1 challenge with each blocker (efficacy control);
(h) 10 pg/mL spike-recovery. Readouts: active TGF-β1 in medium (ELISA + MLEC/PAI-1 bioassay), nuclear
pSmad2, α-SMA stress-fibre fraction.

- Cell-free wells: **H1 → ligand present; H2-H8 → absent.** Basis: assumption + ML11, no source (S-pack gap).
- Cells vs cell-free at day 3: **H2, H3, H6 → increase; H1, H4, H5, H7, H8 → no change.**
- pSmad2 vs never-treated: **H1, H2, H3 → increase; H4, H5, H7, H8 → no change; H6 → not predicted**
  (the senescence source names IL-1β, IL-6, IL-5, IL-10 and no TGF-β1 — S5 / `lit-90bac4ae80b3`).
- α-SMA under continuous SB431542: **H1, H2, H3 → decrease; H4, H5, H6, H7, H8 → no change.** The
  "no change" for H4 is read off S1 (`lit-4003fcca2815`): SD-208 did not dedifferentiate the
  TGF-β1-induced, non-proliferating myofibroblast "despite maintained stress" — a rat cardiac result,
  used here as a cross-species assumption, which is written into the prediction.
- Separates **[VCRP]**: H1 from every other hypothesis, and H2/H3 from H4/H5/H7/H8.
- Cannot separate **[VCRP: E1 `unseparated_pairs`]**: H2 vs H3, H4 vs H5, H4 vs H7, H4 vs H8, H5 vs H7,
  H5 vs H8, H7 vs H8.

### E2 — conditioned medium transfer, transwell, mixed co-culture (the "cell-to-cell" arm)

Donor CM from day 3-5 windows onto naive cells ±1D11; control media are never-treated CM **and** medium
conditioned in cell-free pulsed-and-washed wells.
- CM vs cell-free carryover medium: **H2, H6 → increase; H1, H3, H4, H5, H7, H8 → no change.**
- CM + 1D11 vs CM + isotype: **H1, H2 → decrease; H6 → no change** (its SASP cytokines are not
  neutralised by an anti-TGF-β antibody); H3 → not predicted.
- IL-6 in donor CM: **H2, H6 → increase; others no change** (S5).
- Separates **[VCRP]**: H2 from H4/H5/H7/H8, H6 from H4, H2 from H6, H2 from H3.
- Cannot separate **[VCRP]**: H1 vs H3, H4 vs H5, H4 vs H7, H4 vs H8, H5 vs H7/H8, H7 vs H8. It also
  cannot convert sufficiency into necessity: activating naive cells is not the same claim as
  maintaining the donors (that is E1 arm b). No source in the pack tests paracrine transfer after
  washout, so this whole experiment fills an evidence gap rather than confirming a result.

### E3 — clonal replating, acid wash, cycloheximide chase (cell autonomy)

Day 2 after washout: trypsinise, ± pH-3 glycine wash, replate at 50 cells/cm² on fresh plates.
- Per-cell α-SMA at clonal vs normal density: **H1, H2, H3, H8 → decrease; H4, H5, H6, H7 → no change.**
- Clonal bimodality: **H6, H7 → present; H1-H5, H8 → absent.**
- Assumption check: cycloheximide chase must lower α-SMA if the turnover assumption holds.
- Separates **[VCRP]**: H4 vs H7, H4 vs H8, H4/H5 vs H1/H2/H3, H7 vs H8.
- Cannot separate **[VCRP]**: H1 vs H2 vs H3 (all collapse on dilution), H4 vs H5 (same plastic),
  **H6 vs H7** (both give bimodality) — that pair goes to E6.

### E4 — substrate and tension (the biggest confounder in this design)

Replate onto 1-2 kPa and 20-30 kPa polyacrylamide and plastic, plus restrained / unrestrained 3-D
collagen, ± Y-27632 / blebbistatin.
- α-SMA on soft vs plastic: **H3, H5, H8 → decrease; H1, H2, H4, H6, H7 → no change.**
- GATA6 on soft vs never-treated on soft: **H4 → increase; H5, H1, H8 → no change; H2, H3, H6, H7 → not
  predicted** (nothing in the pack links them to GATA6 — a trace gap I left visible on purpose).
- Separates **[VCRP]**: H4 vs H5 (the pair E1 and E3 cannot), H3 vs H4, H1 vs H3, H4 vs H8.
- Cannot separate **[VCRP]**: H3 vs H5, H1 vs H2, H4 vs H6, H4 vs H7, H6 vs H7, and more.
- Caution from the pack: S2 reports that a **twofold** stiffness drop was not enough — only complete
  release lowered α-SMA — so a modest softening could read "no change" for the wrong reason. And S1
  separates stress-fibre depolymerisation (fast, strain release) from true dedifferentiation (only the
  spontaneous myofibroblast, after long-term 3-D): the readout, not the biology, decides what
  "reversal" means here.

### E5 — ATAC/RNA-seq, HDAC, β1-integrin and formin arms

- ACTA2/SERPINE1 accessibility under continuous receptor block vs vehicle: **H1, H2, H3 → decrease;
  H4, H5, H6, H7, H8 → no change.**
- α-SMA after HDAC inhibition: **H4 → decrease**, and the prediction is labelled in the plan as an
  inference, not the source's result — S3 used HDAC inhibition to *rescue* persistence when β1-integrin
  or mDia2 was blocked, not to erase it. If α-SMA goes *up*, my prediction was wrong, not H4.
- Cannot separate **[VCRP]**: H4 vs H5, H4 vs H6, H5 vs anything downstream, H6 vs H7. Bulk ATAC also
  cannot distinguish an enriched open subpopulation (H7) from a shifted one (H4); single-cell ATAC would be.

### E6 — senescence panel and senolytics (the explanation the question did not name)

- SA-β-gal vs never-treated: **H6, H7 → increase; others no change.**
- α-SMA / SA-β-gal colocalisation vs chance: **H6 → above chance; all others → at chance.** This is the
  readout that separates H6 from H7 **[VCRP]**.
- α-SMA after navitoclax or D+Q: **H6, H7 → decrease; others no change**, with absolute counts reported
  because a senolytic changes the denominator.

### Plan-level coverage

**[VCRP]** No objective unreached, no sub-question unanswered, no hypothesis untested, no readout spec
missing, **no hypothesis pair never separated** — all 28 pairs are separated by at least one experiment,
and no experiment is non-discriminating. That is a statement about the predicted values I wrote, not
about whether the experiments would work: the checker says explicitly that effect size, noise and
interference are not modelled, and that two different predicted values is not a measure of how well a
pair would actually be told apart **[VCRP: `limits`]**.

## 5. Controls that make the readings interpretable

Never-treated cells carried through the identical rinse schedule; carrier vehicle (4 mM HCl/0.1% BSA);
**cell-free pulsed-and-washed wells** (this is what turns "residual ligand" from an assumption into a
measurement); isotype IgG and DMSO; blocker-efficacy arm (acute TGF-β1 challenge with blocker present);
10 pg/mL spike recovery; cell counts and confluence at every harvest, because the arms diverge in
proliferation; gel stiffness verified per batch and fibronectin coating matched across stiffnesses;
restrained vs unrestrained gels side by side; never-treated senolytic arm for toxicity; absolute counts
alongside every percentage; three donors, blinded scoring.

## 6. Decision branches

1. **Active TGF-β1 measurable in the cell-free wells above the spike-recovery floor** → H1 is live;
   redesign the washout (longer, serum-free rinses, fresh plates) or carry the cell-free value as a
   subtraction before interpreting anything else.
2. **Cell-free at floor but cells' medium above never-treated** → maintaining ligand is cell- or
   matrix-derived (H2/H3); E2 and the plasmin/LTBP arms lead, H1 drops.
3. **Continuous receptor blockade from washout changes nothing** → no ligand route is necessary; H4-H7
   lead and E4-E6 become the main line.
4. **Continuous blockade reverses, delayed blockade does not** → there is a closing window: ligand early,
   something self-sustaining later. Both a ligand and an intrinsic-state explanation are then live at
   once, and the question becomes *when* the handover happens, not *which* is true.
5. **CM activates naive cells, 1D11 blocks it** → a secreted TGF-β-family ligand is sufficient on
   neighbours; still needs the necessity arm. **1D11 does not block it, IL-6 up** → non-TGF-β mediator;
   stop buying TGF-β reagents, go to cytokine depletion.
6. **α-SMA persists on 1-2 kPa gel with GATA6 up** → intrinsic memory (H4). **α-SMA falls to
   never-treated on soft** → the stiff plastic was a necessary maintainer (H5), and any "persistent
   state" claim made only on plastic must be restated.
7. **SA-β-gal/p21 up, Ki-67 down, colocalised with α-SMA** → senescence (H6); "reversibility" is the
   wrong frame and clearance is the relevant intervention. **Up but not colocalised** → two
   subpopulations; sort before asking the persistence question again.
8. **Blocker-efficacy control fails, or spike recovery fails** → every negative blockade/ligand result
   in the plan is uninterpretable. Fix the pharmacology or the assay; do not report "no residual ligand".
9. **Cycloheximide barely lowers α-SMA in 24 h** → H8 is live for that endpoint; move weight to mRNA and
   contractility.

## 7. Preconditions: records to check, data to collect, and what depends on what

**Records to check before starting (ordering of *interpretation*, not of pipetting):** the donor, tissue
of origin and passage; the serum concentration during and after washout; the actual stiffness of the
culture surface; the exact day after washout at which "persistence" was scored; the lot and carrier of
the recombinant TGF-β1; and whether previous persistence claims in the lab were measured on plastic
only. These four are submitted as `open_conditions`; the checker lists them back as open, with no
confirmed conditions **[VCRP: `conditions`]**.

**Ordering of data collection (hard order):** E1 first. If residual ligand or ongoing pSmad2 is present,
E3-E5 would be run on a culture that is still being driven, and their results would answer a different
question. E6 can run in parallel on sister wells (cheap, same plates). E5 is last because it is
expensive and only interpretable once the blockade result is in hand.

**Ordering of interpretation (soft order):** α-SMA is interpretable only once the cycloheximide chase
has shown the protein turns over; the senescence panel is interpretable only with absolute counts;
"intrinsic memory" is interpretable only after bimodality (E3) and single-cell structure are addressed —
bulk ATAC alone cannot carry that word.

**What the whole interpretation depends on:** (i) blocker efficacy; (ii) the ligand assay's detection
floor; (iii) α-SMA protein turnover. All three are entered as explicit `assumption_checks`, so an
observation against them marks every prediction that rests on them. **[VCRP]** after the revision, no
prediction trace has a gap: every prediction carries a stated basis, and every assumption-based one
states its assumption.

## 8. The priority experiment, concretely

**E1 — one plate layout, three donors, passage 3-5, 1% serum from 24 h before the pulse.**
Treat with recombinant TGF-β1 **5 ng/mL for 72 h**. Wash out: 3 × PBS rinse, then two full medium
changes 2 h apart, then fresh TGF-β1-free medium. From the moment of washout:

| arm | content |
|---|---|
| a | vehicle (4 mM HCl/0.1% BSA) |
| b | 1D11 pan-TGF-β 10 µg/mL continuous (+ isotype IgG arm) |
| c | SB431542 10 µM continuous (+ DMSO arm) |
| d | SB431542 from day 3 only |
| e | never-treated, identical handling |
| f | **cell-free wells, pulsed and washed exactly as (a)** |
| g | naive cells + acute 5 ng/mL TGF-β1 with each blocker (efficacy control) |
| h | medium spiked with 10 pg/mL TGF-β1 (spike recovery) |

Sample medium at 6 h, day 1, day 3, day 5; fix cells at day 1, 3, 5. Readouts: active TGF-β1 (ELISA on
native and acid-activated medium + MLEC PAI-1-luciferase, pg/mL, per 10⁵ cells, against fresh medium and
arm f); nuclear pSmad2 (IF, ≥300 cells/well, against arm e the same day); α-SMA stress-fibre fraction
(IF + phalloidin, ≥3 decorated fibres crossing the nucleus, blinded, ≥300 cells, against arm e).

**Why first (my judgement, not the checker's — nothing in the output ranks experiments
[VCRP: `limits`]):** it is the only experiment that *measures* the washout instead of assuming it; the
evidence pack contains no source that measures residual exogenous TGF-β1, which makes that the weakest
link in every later interpretation; it carries both measurement-assumption checks; and its result
reorders everything downstream.

## 9. What the plan deliberately leaves open

- **ML11 carries no evidence id and the checker flags it `no_evidence` [VCRP].** Kept that way: it
  marks the pack's real gap rather than hiding it behind a citation that does not say it.
- Every cross-system transfer (rat cardiac → human dermal/lung; valvular interstitial cells; CAFs; MSCs;
  7-day rat exposure at a dose the abstract prints garbled as "10 46 ng/mL") is written into the
  prediction that uses it, as an assumption, not as support.
- Two arms I would add after E1: a **decellularised donor-matrix transfer** (the only clean way to split
  H3 from H2), and **single-cell ATAC** (the only clean way to split H4 from H7).
- No results exist yet. Nothing above is an observation.
