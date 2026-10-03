# Why does the myofibroblast state persist after TGF-β1 washout? An experimental design

Fixed assumptions (from the evidence pack, not confirmed by any user): primary human fibroblasts (dermal or lung) on standard tissue-culture plastic; recombinant TGF-β1 2–5 ng/mL for 48–72 h, then washout into TGF-β1-free medium; the persistent phenotype is α-SMA in stress fibres plus contractility, days after washout. Donor, passage, serum level, substrate stiffness and the exact post-washout day are not fixed.

Source key: S1 Driesen 2014 (spans lit-04139c6d6982, lit-4003fcca2815); S2 Acta Biomater 2016 (lit-0f512e20b35a, lit-b1bf272184af, lit-b0c020392ab5); S3 Adv Sci 2026 CAF chromatin (lit-13f07d427fef, lit-21c2cde4f3dc); S4 Adv Sci 2026 MSC SALL1–GATA6 (lit-de72b3cfc53c, lit-31f9da012da1); S5 Front Pharmacol 2026 senescence (lit-e62f54ed4087, lit-90bac4ae80b3); S6 IJMS 2023 Dupuytren (lit-8ccc91bd45f9, lit-d4c2a13f46ee); S7 JBC 2014 ILD autocrine (lit-91332fe8e2a5, lit-ea0d3890720d); S8 Mechanobiol Med 2025 stiffness (lit-87a281f303a5, lit-086e187e2c2d). "GK" = general knowledge, not in the pack. "A" = explicit assumption.

Important limits up front: no pack source measures residual exogenous TGF-β1 after washout, and no pack source tests paracrine transfer (e.g. conditioned medium). Every statement about those two mechanisms below rests on GK or on design logic, not on evidence. Most pack sources use other cells (rat cardiac, valvular, CAF, MSC) or other inducers (stiffness), so they supply precedents for a mechanism, not predictions of effect size in human fibroblasts.

---

## 1. Goal (restated without narrowing)

After TGF-β1 is removed, primary human fibroblasts still show the myofibroblast phenotype. The goal is to design experiments that tell apart **all plausible explanations** for that persistence — residual treatment material, cell-to-cell signalling, a persistent change of cell state, and any others — and to establish **which of them contribute, in what combination**, rather than to pick one winner. That includes first establishing that the persistence is real and treatment-specific (not a culture or measurement effect), and covering both readouts (α-SMA stress fibres and contractility), which need not persist for the same reason.

---

## 2. Alternative explanations, and how they relate

| ID | Explanation | Source basis |
|---|---|---|
| E0 | **Not treatment-specific persistence: baseline drift.** Fibroblasts on stiff plastic spontaneously become myofibroblasts over time; the "persisting" phenotype is the culture condition, seen also in time-matched untreated cells. | S1 (lit-04139c6d6982: spontaneous p-MyoFb on plastic); S8 (lit-87a281f303a5) |
| E1 | **Residual exogenous TGF-β1.** Ligand not removed by washing: adsorbed to plastic, to BSA/serum carrier proteins, to ECM, bound to cell-surface receptors/co-receptors or in signalling endosomes; keeps signalling after "washout". | GK only; pack explicitly lacks a source |
| E2a | **Autocrine endogenous TGF-β loop.** The pulse induces the cells' own TGF-β production/activation, which sustains signalling. | S7 (lit-91332fe8e2a5: autocrine TGF-β1 in ILD fibroblasts) |
| E2b | **Matrix-stored latent TGF-β.** Cells deposit LAP–TGF-β/LTBP-1 into their ECM during treatment; later activation (and weak degradation of the signal) re-supplies ligand. | S6 (lit-8ccc91bd45f9, lit-d4c2a13f46ee) |
| E2c | **Paracrine non-TGF-β signalling, incl. SASP.** Treated cells secrete other factors (e.g. IL-1β, IL-6) that maintain neighbours' activation. | S5 (lit-90bac4ae80b3: SASP-like secretion after TGF-β1); paracrine transfer itself untested in pack |
| E2d | **Contact-dependent signalling** between treated cells. | GK only |
| E3 | **Persistent cell-intrinsic state change** (chromatin accessibility, lamina–chromatin coupling, a TF circuit) that no longer needs the inducing signal. | S3 (lit-13f07d427fef, lit-21c2cde4f3dc); S4 (lit-de72b3cfc53c, lit-31f9da012da1); S1 (lit-4003fcca2815: TGF-β1-induced non-p-MyoFb did not dedifferentiate under SD-208) |
| E4 | **Senescence.** TGF-β1 drives a stable growth-arrested state with myofibroblast markers and a secretome. | S5 (lit-e62f54ed4087, lit-90bac4ae80b3) |
| E5a | **Mechanical maintenance by the plastic substrate.** Stiff plastic holds contractility/α-SMA once induced. | S8 (lit-87a281f303a5, lit-086e187e2c2d); S2 (lit-b1bf272184af) |
| E5b | **Mechanical self-maintenance via self-deposited/stiffened matrix and tension** (a feed-forward loop: contractile cells build stiff matrix, which keeps them contractile). | S2 (lit-0f512e20b35a, lit-b0c020392ab5: transient stiffening → persistent, "irreversible" activation); S3 (stiff ECM → persistent activation) |
| E6 | **Readout lag.** α-SMA protein and assembled stress fibres turn over slowly; "persistence" at day N is decay not yet complete, with signalling already off. | GK only |
| E7 | **Population composition shift.** The pulse changed which cells are present (differential arrest, death or proliferation; e.g. treated cells stop dividing), so the α-SMA+ fraction remains high without any single cell "remembering". | S1 (TGF-β1 cells were non-proliferating; spontaneous ones proliferated) as precedent for differential proliferation; selection itself GK |

**Coexistence.** Biologically, none of E1–E7 excludes another, and several are expected to chain: E2b/E2a can feed E3 (S3: persistence after stiffness **and** secreted factors); E4 produces E2c (S5); E5b and E3 are linked in S3 (matrix sensing → chromatin). The two readouts may persist for different reasons (e.g. α-SMA from E3, contractility from E5a).

**Where exclusion does exist** (these are the partitions experiments can actually cut):
- **E0 vs treatment-specific persistence:** if time-matched untreated cells are equally α-SMA+/contractile, no treatment-specific persistence exists to explain, and E1–E7 (as explanations of a *treatment effect*) are excluded for that readout.
- **Requires ongoing TGF-β receptor signalling (E1, E2a, E2b) vs does not (E3, E4-core, E5, E6, E7, E2c, E2d):** for a given readout at a given time, the phenotype either does or does not fall when receptor signalling is blocked. Not a mechanism exclusion (both classes can operate) but a measurable split.
- **Source of ligand, exogenous (E1) vs endogenous (E2a/E2b):** as the *sole* source these exclude each other; both can contribute.
- E6 as **sole** explanation excludes stable persistence: E6 predicts eventual decay to the untreated reference; every other treatment-specific explanation predicts a stable plateau above it.

---

## 3. Mechanism versus what would be measured

| ID | Proposed mechanism (what is happening) | What would be measured (observable, not the mechanism) |
|---|---|---|
| E0 | Plastic stiffness alone activates fibroblasts with time in culture | α-SMA stress-fibre fraction and contractility in **untreated** cells at each time point |
| E1 | Leftover exogenous ligand engages TβRII/ALK5 | Active TGF-β in post-wash medium; signalling induced in naive cells by a cell-free "mock-treated" well; dependence on a neutralising antibody/receptor inhibitor; loss on replating to fresh plastic |
| E2a | Cells make and activate their own TGF-β | TGFB1 mRNA, secreted total/active TGF-β1 over days; signalling still present after TGFB1 knockdown before treatment? (should fall) |
| E2b | Latent TGF-β in deposited matrix released later | Naive cells on decellularised matrix from treated cells; dependence on activation (e.g. integrin-αv / protease blockade, GK) |
| E2c | Non-TGF-β secreted factors maintain activation | Conditioned medium (CM) effect on naive cells that is **not** blocked by TGF-β neutralisation/TβRI inhibition; SASP cytokines in CM |
| E2d | Contact signalling | Label-mixed co-culture vs Transwell co-culture |
| E3 | Stable chromatin/TF state independent of input | Persistence after removing ligand **and** matrix **and** substrate cues (replate, inhibitor present); chromatin accessibility at myofibroblast loci (ATAC); dependence on chromatin modifiers |
| E4 | Stable growth arrest with SASP | SA-β-gal, p16/p21, Ki-67/EdU, p-Rb; senolytic sensitivity of the α-SMA+ fraction |
| E5a | Stiff substrate keeps contractile machinery engaged | Persistence on plastic vs soft substrate (inhibitor present), compared with untreated cells on the same substrates |
| E5b | Self-built stiff matrix and tension keep cells activated | Effect of releasing tension (floating vs attached gel) and of removing deposited matrix by replating; long-term follow-up (S1) |
| E6 | Slow protein/fibre turnover | Fast readouts (pSMAD2/3, ACTA2/SERPINE1 mRNA) fall while α-SMA protein lags; eventual decay of protein |
| E7 | Selection / differential proliferation | Cell counts, death (e.g. caspase/LDH), EdU history labelling, per-cell α-SMA distributions rather than means |

---

## 4–6. Experiments, predictions, and what each separates

Common reference arms (used in every experiment unless stated): **U** = untreated, time-matched, same substrate and medium; **C** = TGF-β1 continuously present (positive reference for the induced state); **W** = TGF-β1 pulse then washout + vehicle (the phenomenon). Predictions are stated relative to these.

### X1 (priority). Washout time course with timed TGF-β receptor blockade and ligand neutralisation
Arms: U, C, W; W + TβRI (ALK5) kinase inhibitor from washout; W + inhibitor started late (day 3 post-washout); W + pan-TGF-β neutralising antibody from washout; W + isotype control; U + inhibitor (inhibitor's own effect on baseline); inhibitor validity control (inhibitor added with fresh TGF-β1 to naive cells). Full specification in section 9.

| Explanation | Prediction in X1 (vs reference) | Basis |
|---|---|---|
| E0 | W ≈ U at every time point (both elevated); no treatment-specific signal to explain | S1 lit-04139c6d6982; S8 |
| E1 | pSMAD2/3 in W stays above U after washout; inhibitor and antibody from washout drop pSMAD2/3 and, over days, α-SMA/contractility towards U; signal strongest early and declining | GK (no pack source) |
| E2a/E2b | Same as E1 for inhibitor; pSMAD2/3 in W sustained or rising later (endogenous supply); antibody effect may be partial for E2b (matrix-bound/locally activated ligand may be poorly accessible, GK) | S7 lit-91332fe8e2a5; S6 lit-8ccc91bd45f9 |
| E2c/E2d | pSMAD2/3 in W returns to U, but α-SMA stays; inhibitor/antibody do not reverse | S5 lit-90bac4ae80b3 (SASP exists); transfer untested |
| E3 | pSMAD2/3 returns to U; α-SMA stress fibres and contractility persist in W ± inhibitor; late inhibitor no different from early | S1 lit-4003fcca2815 (SD-208 did not dedifferentiate TGF-β1 non-p-MyoFb); S3; S4 |
| E4 | As E3, plus low EdU/Ki-67 in W | S5 lit-e62f54ed4087 |
| E5a/E5b | As E3 on plastic (inhibitor does not reverse) — X1 cannot distinguish them from E3 | S8; S2 |
| E6 | pSMAD2/3 and ACTA2/SERPINE1 mRNA return to U quickly; α-SMA protein declines slowly toward U in W and W+inhibitor alike | GK |
| E7 | Per-cell distributions show a subpopulation shift; total cell number differs W vs U | GK; S1 (non-proliferating TGF-β1 cells) |

**Separates:** E0 from treatment-specific persistence; ligand-/receptor-dependent (E1, E2a, E2b) from receptor-independent (E2c, E2d, E3, E4, E5, E7); E6 from stable states (by time course). **Cannot separate:** E1 from E2a/E2b (all need receptor signalling); E3 from E4, E5a, E5b, E2c, E2d. Caveat: reversal by the inhibitor does not prove E1/E2 *alone* — an intrinsic state (E3) may still require basal autocrine signalling to be expressed. Non-reversal is interpretable only if the validity control shows full blockade of fresh TGF-β1 at the dose used. Note also S1: on strain release, stress fibres depolymerised in both reversible and irreversible cells (lit-4003fcca2815), so loss of fibres alone is not dedifferentiation; read fibres, transcripts and contractility together.

### X2. Residual exogenous ligand versus endogenous ligand
Run if X1 shows receptor dependence (can be collected in parallel; see section 8).
- **X2a Cell-free mock well:** TGF-β1 at the same dose/medium/duration in a well without cells, washed identically; then seed naive fibroblasts. Read pSMAD2/3 (1–24 h) and α-SMA (72 h) vs a never-treated well.
- **X2b Replate to fresh plastic:** after washout, trypsinise W cells and replate onto fresh plastic in fresh medium (removes plastic- and matrix-adsorbed ligand); compare with W cells left in place. Same handling for U.
- **X2c Medium assay:** total vs active TGF-β1 (ELISA without/with acid activation, GK) in medium collected at 0–24 h, 24–72 h, 72–144 h after washout; optional reporter-cell bioassay of the same medium (GK).
- **X2d Knockdown of endogenous TGFB1** (siRNA, verified) before the pulse: post-washout ligand can then only be exogenous (or from serum).
- **X2e Decellularised matrix transfer:** naive cells on matrix deposited by W vs U cells (tests E2b; also carries E5b matrix stiffness).

| Explanation | Prediction | Basis |
|---|---|---|
| E1 | X2a mock well activates naive cells; X2b replating removes the signalling; X2c active TGF-β highest in earliest window then falls; X2d knockdown does not remove post-washout signalling | GK |
| E2a | X2a negative; X2b signalling returns after replating; X2c total/active TGF-β1 rising later; X2d knockdown removes it | S7 |
| E2b | X2a negative; X2e matrix from W activates naive cells, blocked by neutralisation/TβRI inhibitor; X2b replating reduces it | S6 |
| E5b | X2e matrix from W activates naive cells **not** blocked by TβRI inhibitor | S2; S3 |

**Separates:** E1 from E2a and E2b; E2b (ligand in matrix) from E5b (matrix mechanics) when X2e is run ± inhibitor. **Cannot separate:** ligand from serum (latent TGF-β in serum, GK) from E2 unless a serum-matched no-cell control is included; X2d tests only TGFB1, not TGF-β2/3.

### X3. Cell-to-cell signalling: conditioned medium and co-culture
- **X3a CM transfer:** CM from W and U cells (collected over defined windows after washout, as X2c) onto naive fibroblasts, each ± pan-TGF-β antibody and ± TβRI inhibitor. Readouts on recipients: pSMAD2/3, ACTA2 mRNA, α-SMA fibres at 72 h.
- **X3b Transwell co-culture** of W cells with naive recipients (shared medium, no contact) vs **X3c labelled mixed co-culture** (contact).
- Measure SASP-type cytokines in CM (e.g. IL-6, IL-1β, as named in S5).

| Explanation | Prediction | Basis |
|---|---|---|
| E1 | Early-window CM activates recipients, blocked by antibody/inhibitor; activity declines with later windows | GK |
| E2a | CM activity persists/increases in later windows, blocked by antibody/inhibitor | S7 |
| E2c | CM activates recipients **not** blocked by antibody/inhibitor; cytokines elevated | S5 (secretome); transfer untested in pack |
| E2d | Mixed co-culture activates neighbours; Transwell does not | GK |
| E3/E4/E5 | CM and Transwell do not activate recipients beyond U-CM | S1, S3, S4, S8 |

**Separates:** secreted (E1/E2a/E2c) from contact (E2d) from non-transmissible (E3/E4/E5/E6/E7); TGF-β-dependent from non-TGF-β paracrine. **Cannot separate:** E1 from E2a without X2 (window and knockdown); autocrine signalling that acts within the producing cell's immediate surface and never reaches bulk medium (GK); a recipient-cell response requires that naive cells be competent, so a negative CM result does not rule out autocrine maintenance in the producing cells.

### X4. Mechanical maintenance: substrate and tension
- **X4a Soft vs stiff:** after washout, replate W and U cells onto soft (A: ~1–5 kPa, GK) and stiff (plastic or ~50+ kPa) substrates of the same coating, with TβRI inhibitor present to remove ligand effects; read at d3, d7, d14.
- **X4b Tension release:** W and U cells in attached (restrained) vs floating (released) collagen gels; follow beyond the acute release for long-term state (S1: "Only p-MyoFb showed true dedifferentiation after long-term 3-D cultures"); then return released cells to a stiff surface without TGF-β1 and test whether the phenotype re-emerges faster in W than U (state memory).

| Explanation | Prediction | Basis |
|---|---|---|
| E0 | U on stiff ≈ W on stiff; both low on soft | S8; S1 |
| E5a | W on soft falls to U-soft; W on stiff stays high | S8; S2 lit-b1bf272184af |
| E5b | Floating gel reverses W; replating off own matrix reduces it | S2 lit-b0c020392ab5 (complete freeing, not twofold reduction, gave α-SMA loss) |
| E3/E4 | W on soft stays above U-soft; stress fibres may depolymerise on release but the state (transcripts, re-emergence on stiff, contractility on return) persists | S1 lit-4003fcca2815; S4 lit-de72b3cfc53c (memory after switch to soft) |

**Separates:** E5a/E5b from E3/E4. **Cannot separate:** E3 from E4 (both substrate-independent); also, replating is itself a perturbation, and partial stiffness reductions may not reveal E5 (S2: twofold decrease did not reverse), so a "persists on soft" result depends on the soft condition being soft enough (A).

### X5. Cell-state characterisation: senescence, chromatin, composition
- **X5a Senescence:** SA-β-gal, p16, p21, Ki-67, EdU, p-Rb in W vs U vs C; senolytic test (navitoclax or dasatinib+quercetin as used in S5; doses GK/titrated) and ask whether the α-SMA+ fraction is selectively removed.
- **X5b Chromatin:** ATAC-seq / targeted accessibility at ACTA2 and other myofibroblast loci in U, C, W (d7); HDAC inhibitor applied after washout as a perturbation. Pack basis is limited: in S3, blocking integrin/formin pathways *prevented* persistent activation and HDAC inhibition *rescued* that prevention (lit-21c2cde4f3dc); S4 identifies GATA6 as a keeper of memory in MSCs. The direction of an HDAC-inhibitor effect in post-washout human fibroblasts is therefore not predicted by the pack.
- **X5c Composition:** EdU pulse during treatment then chase; cell counts and death through washout; single-cell α-SMA distributions; optional clonal tracking.

| Explanation | Prediction | Basis |
|---|---|---|
| E3 | W retains C-like accessibility at myofibroblast loci at d7 despite pSMAD2/3 at U level; proliferation not necessarily low | S3; S4 |
| E4 | SA-β-gal/p16/p21 up, Ki-67/EdU/p-Rb down; senolytics reduce α-SMA+ fraction | S5 lit-e62f54ed4087 |
| E7 | Shift in cell number/death; α-SMA+ cells are the non-dividing EdU-negative fraction while dividing cells revert | S1 (non-proliferating TGF-β1 cells); GK |
| E6 | No persistent accessibility change; protein decays | GK |

**Separates:** E4 from E3; E7 from a per-cell state. **Cannot separate:** chromatin change as cause vs consequence of sustained signalling without combining with X1 inhibitor arms; senolytic effects may be non-specific toxicity (needs U + senolytic control).

---

## 5. Controls (across experiments)

- **U, time-matched, same substrate, same serum and medium changes** — required for E0 and for every comparison (S1, S8).
- **C (continuous TGF-β1)** — defines the full induced state and the upper reference.
- **Vehicle controls** for every inhibitor (DMSO matched); **isotype control** for the neutralising antibody.
- **Inhibitor validity control:** inhibitor added with fresh TGF-β1 (same dose as the pulse) to naive cells must block pSMAD2/3 and ACTA2 induction; without this, non-reversal in X1 is uninterpretable.
- **U + inhibitor/antibody/senolytic** — effect of each agent on untreated cells (baseline/toxicity).
- **Washout verification:** cell-free mock well (X2a) and serum-only medium in no-cell wells (serum latent TGF-β, GK).
- **Matrix controls:** decellularised U matrix alongside W matrix (X2e).
- **Substrate controls:** U on each substrate (X4).
- **Readout controls:** pre-treatment baseline for each donor; identical imaging/quantification blind to arm; per-cell scoring (fraction of cells with α-SMA incorporated into stress fibres, not total α-SMA intensity alone).
- **Biological replication:** ≥3 donors (A), because donor is not fixed; passage range recorded and matched.

---

## 7. Decision branches

1. **W ≈ U for a readout (X1)** → no treatment-specific persistence for that readout; conclude E0 (plastic-driven activation, S1/S8). Do: move the question to a softer substrate where U is low, then repeat X1 there before any further experiment.
2. **W > U; pSMAD2/3 and mRNAs return to U and α-SMA protein declines steadily toward U by the last time point, regardless of inhibitor** → E6 (readout lag). Do: extend time course; report as transient, not persistent.
3. **W > U; pSMAD2/3 stays elevated and inhibitor/antibody from washout returns readouts toward U** → ongoing receptor signalling required (E1 and/or E2a/E2b). Do X2 to find the source:
   - mock well positive / replating removes it / early-window active TGF-β, knockdown does not abolish → E1 dominant: fix the washout protocol (A: more washes, carrier-free ligand, replating) and retest whether anything persists afterwards.
   - mock well negative, signalling returns after replating, knockdown abolishes → E2a. Then X3a to see if it is transmissible.
   - W matrix activates naive cells, inhibitor-sensitive → E2b (S6).
   - Late inhibitor also reverses → loop still active at day 3; if late inhibitor fails while early succeeds → a ligand-dependent phase that has converted into a ligand-independent one (E3 established during that window). Do X5b at those time points.
4. **W > U; pSMAD2/3 at U level; inhibitor (validated) does not reverse** → receptor-independent persistence (E2c, E2d, E3, E4, E5, E7). Do in parallel: X4 (mechanics), X5a/X5c (senescence/composition), X3 (non-TGF-β paracrine).
   - Reverses on soft/after release, U similar → E5a/E5b; then X2e ± inhibitor to separate matrix ligand from matrix mechanics.
   - Persists on soft and after release, senescence markers up, senolytic-sensitive → E4.
   - Persists on soft, not senescent, chromatin retains C-like state → E3; then X5b perturbations.
   - CM transfers activation not blocked by TGF-β antagonism → E2c; identify cytokines.
5. **Readouts disagree (e.g. α-SMA persists but contractility reverts, or vice versa)** → treat each readout as a separate question; do not merge into one conclusion (e.g. S1: stress fibres can depolymerise without dedifferentiation).
6. **Inhibitor validity control fails** → stop; titrate inhibitor/choose another (e.g. SD-208 as in S1) before interpreting X1.

---

## 8. Preconditions

**Records to check (before designing, from existing lab records):**
- TGF-β1 source, lot, carrier (BSA-containing vs carrier-free), exact dose and duration used when the persistence was first seen.
- Washout procedure: number of washes, wash solution, volumes, whether medium was fully replaced, whether cells were replated.
- Serum type/percentage and lot (serum carries latent TGF-β, GK); medium change schedule after washout.
- Donor, tissue (dermal vs lung), passage, time on plastic before treatment, plating density, confluence at washout.
- Whether an untreated time-matched control was run and what it showed (if not, E0 cannot yet be excluded for the original observation).
- How "persistence" was read (which day, which method, per-cell vs bulk).

**Data that must be collected:**
- Pre-treatment baseline per donor (α-SMA fibres, contractility).
- Time course after washout (d0, d1, d3, d7; d14 if E6 is plausible) with fast (pSMAD2/3, ACTA2/SERPINE1 mRNA) and slow (α-SMA protein, stress fibres, contraction) readouts.
- Inhibitor validity data at the dose used.
- Cell counts/death/proliferation through the time course (E7, E4).

**Dependencies — and which kind of ordering they are:**
- *Ordering of data collection (must happen in time order; cannot be recovered later):* baseline before treatment; U collected concurrently with W at each time point (not historical); conditioned medium and matrix collected from the same washout cultures in defined windows; TGFB1 knockdown established before the pulse.
- *Ordering of interpretation (data can be collected in parallel, but meaning depends on another result):* X1 non-reversal is interpretable only after the inhibitor validity control; any treatment-specific conclusion depends on E0 being excluded (W > U); X2 is interpreted only if X1 shows receptor dependence, and X4/X5 are interpreted mainly if it does not — but X2–X5 arms can be run alongside X1 from the same washout to save time, at the cost of some unused arms.
- *Assumption dependence:* interpretations of X4 depend on the soft substrate being soft enough (A; S2 shows partial reductions may not reverse); all mechanism precedents come from other cell types/inducers (S1–S5) and transfer to human dermal/lung fibroblasts is an assumption.

---

## 9. Priority (first) experiment: X1, and why

**Why first.** (i) It contains the E0 test (time-matched U on the same plastic), without which no other result has a treatment effect to explain (S1, S8). (ii) It cuts the candidate set at its most informative joint — receptor-dependent (E1, E2a, E2b) vs receptor-independent (E2c–E7) — and directly addresses the first named explanation family (residual material) and the ligand route of the second. (iii) Its time course separates E6 from stable persistence. (iv) It is cheap, uses standard reagents and assays, and its outcome decides whether X2 or X4/X5 comes next. S1 provides a precedent that the TGF-β1-induced state may not reverse under receptor kinase blockade (lit-4003fcca2815), which makes the receptor-independent branch a real possibility rather than a formality — but S1 used rat cardiac cells and its dose/follow-up are not given.

**Design (doses from the pack where available; others GK, to be titrated):**
- Cells: primary human fibroblasts, ≥3 donors, matched low passage, plated on tissue-culture plastic at a sub-confluent density; same serum percentage throughout (A: keep the lab's standard; record it).
- Induction: TGF-β1 **5 ng/mL for 48 h** (upper end of the pack range; optional second dose 2 ng/mL to check dose dependence). Carrier noted.
- Washout (day 0): remove medium, 3 washes with warm PBS + 1 wash with medium, then fresh TGF-β1-free medium (A). Medium changed with the agents at d1, d3, d5.
- Arms (each per donor, technical triplicates):
  1. U (vehicle)
  2. C (TGF-β1 maintained, 5 ng/mL)
  3. W + vehicle (DMSO matched)
  4. W + ALK5 inhibitor from washout: SB-431542 **10 µM** (GK); SD-208 as an alternative (used in S1, dose not stated in pack)
  5. W + same inhibitor started at d3
  6. W + pan-TGF-β neutralising antibody (e.g. 1D11-type, ~10 µg/mL, GK) from washout
  7. W + isotype control antibody
  8. U + inhibitor
  9. Validity: naive cells + fresh TGF-β1 5 ng/mL + inhibitor (and + antibody), read at 1 h (pSMAD2/3) and 24 h (ACTA2)
  10. Cell-free mock well (TGF-β1 + identical washout), seeded with naive cells at d0 — a cheap early probe of E1 carried in from X2a
- Time points: end of pulse (d0, pre-wash), 1 h and 24 h post-wash (pSMAD2/3), d1, d3, d7 (all readouts); d14 for arms 1, 3, 4 if α-SMA is still declining at d7.
- Readouts:
  - pSMAD2/3 (western with total SMAD2/3, or nuclear IF) — fast indicator of ongoing receptor signalling.
  - qPCR: ACTA2, SERPINE1, COL1A1, TGFB1.
  - α-SMA immunofluorescence with phalloidin: per-cell fraction with α-SMA incorporated into stress fibres; scored blind.
  - α-SMA western (normalised).
  - Contractility: collagen gel contraction with cells lifted from each arm at d3 and d7 and embedded with the arm's agent maintained (replating applied identically to all arms; A), and/or traction force microscopy if available (S8 used TFM).
  - Cell number, EdU incorporation, and a death marker (feeds E7/E4 triage).
- Analysis: compare each arm with U and C per donor; primary contrasts are W vs U (E0), W+inhibitor vs W (receptor dependence), early vs late inhibitor (phase conversion), and the slope of α-SMA over d1–d7 in W vs W+inhibitor (E6). Thresholds for "reversal" (e.g. return to within U's donor-matched range) should be fixed before unblinding (A).

**What it will not answer:** whether receptor-dependent signalling comes from residual exogenous or endogenous ligand (→ X2), and which receptor-independent mechanism holds the state (→ X3–X5). These are planned in section 7 and can be started from the same washout cultures.
