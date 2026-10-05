# Pre-registration: ERK→RAF feedback under MEK inhibition (logic_biology_v1, prereg-1)

Written and hashed before any model run and before the results sections of the comparison paper
were read. `case.json` beside this file is the machine-readable form. Where the two differ,
`case.json` is the version that was run.

## What this is, and what it is not

The question: does a five-node Boolean candidate model, built from published statements, give
the same directions as the observations reported when a MEK inhibitor is added to colorectal
cancer cell lines? The models are the RAS–RAF–MEK–ERK cascade with ERK-dependent negative
feedback. Those observations were reported by Fritsche-Guenther et al. 2011.

This is a **retrospective reproduction and applicability assessment of published observations**
(공개된 관찰의 후향적 재현·적용성 평가). It is not a holdout, blinded or independent test. The
following were seen before the model was fixed, and the base model agrees with them:
- the paper's title and every section title;
- two abstracts from related systems.

See category C.

## Selection (3 candidates, 1 chosen)

| Candidate | Source found | Full text | Decision |
|---|---|---|---|
| Pratilas et al. 2009 PNAS, RAF feedback in RTK vs BRAF V600E tumour cells (doi 10.1073/pnas.0900780106, PMID 19251651) | VCRP search | not available (VCRP), empty body (PubMed) | used for one rule (abstract only) |
| Lito et al. 2012 Cancer Cell, relief of ERK feedback by RAF inhibitors in BRAF V600E melanoma (doi 10.1016/j.ccr.2012.10.009, PMID 23153539) | VCRP search | not available (VCRP) | used for the alternative rule (abstract only) |
| **Fritsche-Guenther et al. 2011 Mol Syst Biol**, "Strong negative feedback from Erk to Raf confers robustness to MAPK signalling" (doi 10.1038/msb.2011.27, PMID 21613978, PMC3130559) | VCRP search | open access, CC BY-NC-SA 3.0, 25 sections | **chosen**: it reports MEK-inhibitor observations on four readouts that a five-node model can name, in cell lines of two genotypes |

Why this case:
- The intervention (a MEK inhibitor) maps to one input.
- The readouts (pMEK, pERK, phospho-Raf-1, active Ras) map to model states.
- The two genotypes (KRAS-mutant, BRAF-mutant) are two scenarios with no new rules.
- The question that separates the two candidate feedback sites (RAF vs RAS) is answerable from
  the same readouts.

Scope:
- one paper's MEK-inhibitor observations;
- two genotype groups;
- four readouts, plus one question pre-declared non-comparable.

Nothing about dose–response, kinetics, robustness to ERK level, or the paper's ODE model.

## Sources and their category

**A** (used to construct the model) and **C** (seen before the model was fixed) are listed here.
**B** is the results text, read only after this file is hashed and committed.

| Evidence id | Source | Part | What it says (short) | Category | Used for |
|---|---|---|---|---|---|
| `lit-cfe8783d78f4` | Fritsche-Guenther 2011, Cells and cell culture | methods | SW480, HCT116, HT29, RKO, LIM1215; 10% fetal calf serum | A | GF input; cell lines |
| `lit-8c09a32b24d6` | same, Cells and cell culture | methods | Caco2 inducible HA-B-Raf; HEK Raf-ER | A | systems with no scenario |
| `lit-e9c4f50cc489` | same, Immunoblotting | methods | antibodies to pErk1/2 T202/Y204, phospho-Raf-1 S289/S296/S301, pan-Ras | A | readouts |
| `lit-fa0c82fe5ac1` | same, Immunoblotting | methods | quantification relative to controls | A | readout direction vs control |
| `lit-b23dff1044ed` | same, Immunoblotting | methods | "the effect of the MEK inhibitor on the feedback phosphorylation of Raf-1" (no direction stated) | A and C | R_FB; seen |
| `lit-12e26e4913bb` | same, Bio-Plex assay | methods | U0126 (several concentrations), 1 µM AZD6244, cycloheximide, actinomycin D, 4OHT, FGF2; P-Mek1 S217/S221 beads | A | MEKi input; pMEK readout; O6 |
| `lit-6100b8bafe2d` | same, Ras activity assay | methods | GST-Raf-1-RBD pulldown after 2 h AZD6244 | A | RAS readout |
| `lit-a9e71dcef163`, `lit-414b88164cb8`, `lit-f334a97ab5aa`, `lit-1df44d553c97`, `lit-5e0735af8e4e` | same, Introduction | intro | robustness to protein-level noise; aim of the study | C | not used for a rule |
| (titles) | same, title and section list | — | Erk→Raf negative feedback; "In Ras-mutated cells, Raf-1 is feedback controlled whereas Ras is not"; "Efficiency of small-molecule inhibitors is impaired by strong negative feedback"; "Feedback is fast and does not require translation or transcription"; DUSP transcriptional feedback not involved | **C** | not cited by a rule, but seen; M1 agrees with them |
| `lit-8c8245921a71` | Pratilas 2009, abstract | abstract | RAF signaling feedback down-regulated in RTK cells, insensitive to it in BRAF-mutant tumours | A (and C for O2) | M1_R_RAF |
| `lit-453db638b05b` | Lito 2012, abstract | abstract | in BRAF V600E melanoma, ERK-dependent feedback suppresses ligand-dependent signaling and Ras function; RAF inhibition increases Ras-GTP | A (and C for O5 in the alternative) | M2_R_RAS |

Licences:
- Fritsche-Guenther 2011 is CC BY-NC-SA 3.0 (attribution, non-commercial, share-alike). This
  record keeps only evidence ids, locators and short phrases, not the text.
- The two abstracts carry no licence in the record. Only a one-line paraphrase and the
  identifiers are kept.

## Rules, evidence and assumptions

Every rule is a host candidate (`stated_by: host`), unvalidated. A strengthening is marked as
one.

| Rule | M1 | M2 | Evidence | What the source says | What the rule adds (assumption) |
|---|---|---|---|---|---|
| RAS | `GF OR KRASmut` | `(GF AND NOT pERK) OR KRASmut` | `lit-cfe8783d78f4`; M2 also `lit-453db638b05b` | 10% serum in culture; (M2) feedback suppresses Ras function in BRAF V600E melanoma | serum = continuous GF; KRAS mutant = RAS always active (general knowledge); M2: a complete veto, in a different tissue |
| RAF | `(RAS AND NOT pERK) OR BRAFmut` | `RAS OR BRAFmut` | M1: `lit-8c8245921a71` | RAF signaling is feedback *down-regulated* in RTK cells; BRAF-mutant is *insensitive* | down-regulation stated as a complete veto; insensitive stated as RAF sufficient on its own; RAS active treated as sufficient for RAF (binding is not activation) |
| pMEK | `RAF` | same | none | — | MEK phosphorylation needs RAF only; **the MEK inhibitor does not block RAF→MEK phosphorylation** (intervention mapping) |
| pERK | `pMEK AND NOT MEKi` | same | none | — | complete MEK-kinase block at the doses used |
| pRaf1fb | `pERK` | same | `lit-b23dff1044ed` | "feedback phosphorylation of Raf-1", effect of MEK inhibitor, no direction | the sites depend on active ERK (general knowledge); a readout node, not the feedback mechanism |

Logical overreach avoided, and where it is not:
- "Down-regulated" and "suppresses" are decreases. Stating them as `NOT pERK` (a complete veto)
  is a strengthening, listed as an assumption.
- RAS → RAF is written as sufficiency; nothing read shows it.
- No rule is derived from necessity alone.

## The key unknown and its one alternative

The key unknown is **where the ERK-dependent feedback acts**. In M1 it acts on RAF; in M2 on
input-driven RAS. Everything else is shared. M2 is a sensitivity check: it is fixed here
with M1 and will not be changed after computing.

## Scenarios, initial state, steps and window

- Initial state:
  - all five internal components are `unknown`, giving 32 cases;
  - scenario and baseline share them, so each case is paired.
- Inputs are constant over the whole run:

  | Scenario | GF | KRASmut | BRAFmut | MEKi |
  |---|---|---|---|---|
  | `KRAS_control` | on | on | off | off |
  | `KRAS_MEKi` | on | on | off | on |
  | `BRAF_control` | on | off | on | off |
  | `BRAF_MEKi` | on | off | on | on |

- Comparisons:
  - `KRAS_MEKi` vs `KRAS_control`;
  - `BRAF_MEKi` vs `BRAF_control`.
- Steps:
  - 24 synchronous updates;
  - reading window: steps 18–24.

  A step is a logical update. No step is converted to a time.
- Genotype groups (general knowledge, an assumption):
  - KRAS-mutant: SW480, HCT116;
  - BRAF V600E: HT29, RKO;
  - no scenario: LIM1215, Caco2-B-Raf, HEK Raf-ER.
- Limits: `max_cases` 256 (32 used); engine limits 32 components, 100 steps.

## Readouts (identity mapping only)

| Readout | Model state | Assay (span) |
|---|---|---|
| `pMEK1_S217_S221_BioPlex` | pMEK | Bio-Plex P-Mek1 S217/S221 (`lit-12e26e4913bb`) |
| `pERK1_2_T202_Y204_WB` | pERK | immunoblot (`lit-e9c4f50cc489`) |
| `pRaf1_S289_S296_S301_WB` | pRaf1fb | immunoblot (`lit-e9c4f50cc489`) |
| `RasGTP_RBD_pulldown` | RAS | RBD pulldown, 2 h AZD6244 (`lit-6100b8bafe2d`) |

## Questions to compare (fixed)

| Id | Readout | Group | Intervention |
|---|---|---|---|
| O1 | pMEK | KRAS | MEK inhibitor vs untreated |
| O2 | pMEK | BRAF | MEK inhibitor vs untreated |
| O3 | pERK | KRAS | MEK inhibitor vs untreated |
| O4 | phospho-Raf-1 S289/296/301 | KRAS | MEK inhibitor vs untreated |
| O5 | active Ras | KRAS | AZD6244 2 h vs untreated |
| O6 | pMEK | any | MEK inhibitor + cycloheximide or actinomycin D vs MEK inhibitor alone; **pre-committed 비교 불가** (no translation/transcription node) |

## Readings and classes (fixed)

**Strict (primary).**
- Take the engine's per-case paired direction for the readout at each window step.
- If one direction holds in every case at every window step, that is the model's direction.
- Otherwise the model's direction is undetermined.

**Ordinal (secondary, a host aggregation).**
- Per case and side, the readout over the window is classified as one of:
  - always active;
  - intermittent;
  - always inactive.
- The two sides are compared by that order.
- If every case gives the same direction, that is the model's direction; otherwise it is
  undetermined.
- Assumption: an intermittent state reads as an intermediate population level. This is not
  shown.

**Classes.**
- **부합:** the text read states a direction for the question in a cell line of its group, and
  it is the model's direction.
- **불일치:** both directions are determinate and they differ.
- **미결정:** the text states a direction; the model's is undetermined.
- **비교 불가:** the direction is not in the text read (figure-only counts as not read); or there
  is no scenario for the cell system; or there is no mapping for the intervention or readout.

**Further rules.**
- One row per statement.
- Magnitude is compared for direction only.
- Times are recorded, not converted.
- Unregistered statements are listed and not scored.
- Every row stays in every denominator.

## Reading plan for B

Read results sections of Fritsche-Guenther 2011 only after this file and `case.json` are hashed
and committed, as few as needed:
- sec-14, "Efficiency of small-molecule inhibitors…";
- sec-11, "In Ras-mutated cells…";
- sec-15, "Feedback is fast…".

Further sections only if a question has no statement there. Figures, tables and supplements are
not read.
