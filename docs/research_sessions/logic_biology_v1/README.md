# ERK→RAF feedback under MEK inhibition: applying a candidate Boolean model to published observations

This is a **retrospective reproduction and applicability assessment of published observations**
(공개된 관찰의 후향적 재현·적용성 평가). It is not a holdout, blinded or independent test. The
paper's title and section titles state its conclusions, and they were seen before the model was
fixed (category C). The base model agrees with them.

The engine was not changed. Product source changes: 0 lines.

## 1. Question and case

**Question.** A small Boolean model of the RAS–RAF–MEK–ERK cascade has an ERK-dependent
negative feedback. Under `run_logic_model`, does it give the directions reported when a MEK
inhibitor is added to colorectal cancer lines? Two genotypes are compared:
- KRAS-mutant: HCT116, SW480;
- BRAF V600E: HT29, RKO.

**Case.** Fritsche-Guenther et al. 2011, *Mol Syst Biol* 7:489, "Strong negative feedback from
Erk to Raf confers robustness to MAPK signalling":
- doi 10.1038/msb.2011.27, PMC3130559;
- licence CC BY-NC-SA 3.0.

Only evidence ids, locators and short paraphrases are kept here; no full text is stored.
Selection and scope are in `prereg/PREREG.md`.

## 2. Rules versus host assumptions

| Rule | M1 (base) | M2 (alternative) | Rests on | Host strengthening |
|---|---|---|---|---|
| RAS | `GF OR KRASmut` | `(GF AND NOT pERK) OR KRASmut` | `lit-cfe8783d78f4` (10% serum); M2 also `lit-453db638b05b` (Lito 2012 abstract, melanoma) | serum = continuous input; KRAS mutant always on (general knowledge); M2: "suppresses" stated as a complete veto |
| RAF | `(RAS AND NOT pERK) OR BRAFmut` | `RAS OR BRAFmut` | `lit-8c8245921a71` (Pratilas 2009 abstract, RTK and BRAF tumour lines) | "down-regulated" stated as a complete veto; "insensitive" stated as sufficient; RAS active treated as sufficient for RAF (binding is not activation) |
| pMEK | `RAF` | same | none | the MEK inhibitor does not block RAF→MEK phosphorylation |
| pERK | `pMEK AND NOT MEKi` | same | none | complete block at the doses used |
| pRaf1fb | `pERK` | same | `lit-b23dff1044ed` (names it feedback phosphorylation; no direction) | the sites depend on active ERK; a readout node, not the mechanism |

- No rule was taken from this paper's results text: that text was read after the model was
  fixed.
- Two rules (pMEK, pERK) carry no evidence id at all.
- The model components are the same in M1 and M2. Only the RAS and RAF rules differ (tested).

## 3. Intervention and readout mapping

**Intervention.**
- U0126 and AZD6244 are one input, `MEKi`. It is on from step 0 for the whole run.
- Doses (several U0126 concentrations; 1 µM AZD6244) are not represented.

**Comparisons.**
- `KRAS_MEKi` vs `KRAS_control`;
- `BRAF_MEKi` vs `BRAF_control`.

Both sides use the same 32 unknown initial states, so each case is paired.

**Readouts.** All are identity mappings:

| Readout | Model state | Assay |
|---|---|---|
| Bio-Plex P-Mek1 S217/S221 | pMEK | `lit-12e26e4913bb` |
| immunoblot pErk1/2 T202/Y204 | pERK | `lit-e9c4f50cc489` |
| immunoblot phospho-Raf-1 S289/S296/S301 | pRaf1fb | `lit-e9c4f50cc489` |
| GST-Raf-1-RBD pulldown | RAS | `lit-6100b8bafe2d` |

**Steps and window.**
- 24 synchronous steps.
- Reading window: steps 18–24.
- No step is converted to a time.

**Readings.**
- **Strict (primary):** the engine's per-case paired direction must be the same in every case
  at every window step.
- **Ordinal (secondary, host aggregation):** per case, the window is classified as one of
  always active, intermittent or always inactive; the classes are then compared.

## 4. When things were fixed, and A/B/C

| Time (UTC) | Event |
|---|---|
| before 13:20 | searches and reads for A/C: methods sections, introduction, two abstracts, titles |
| 13:22:25 | `prereg/case.json` and `prereg/PREREG.md` committed (`d37c0b4`), hashed in `prereg/SHA256SUMS` |
| 13:22:27 | pushed to the branch |
| after 13:22:27 | results sections sec-14, sec-11, sec-15, sec-10 read (B) |
| then | observations recorded (`observations.json`), then the first model run |

**A — construction:**
- methods spans (cells, immunoblotting, Bio-Plex, Ras assay);
- the Pratilas and Lito abstracts.

**B — comparison:**
- results spans `lit-e5530dbcdbdc`, `lit-69aab6e67fdb`, `lit-56693f038783`, `lit-5064dfff5a42`,
  `lit-4a9493f38afd`, `lit-faa620143614`, `lit-e87187c7b35e`, `lit-1fd73f7e342a`,
  `lit-03d068babab3`, `lit-ede2f3f02921`, `lit-7bd2d4075c0e`, `lit-395c8b700e26`.
- A test checks that none of them appears in the pre-registration.

**C — seen before fixing.** These are the titles that state the findings:
- "Erk to Raf" feedback;
- "In Ras-mutated cells, Raf-1 is feedback controlled whereas Ras is not";
- "Efficiency of small-molecule inhibitors is impaired…";
- "Feedback is fast and does not require translation or transcription".

Also seen: the methods phrase "the effect of the MEK inhibitor on the feedback phosphorylation of
Raf-1", and the Pratilas abstract (BRAF-mutant RAF is insensitive to feedback). So the
agreement of O1, O2, O4 and O5 with M1 is **not** independent of what the model was built from.

**After fixing:**
- No model, scenario, readout, window or class rule was changed after B was read.
- One script fix was made before results were inspected for a decision. The O6 rows had been
  shown the MEK-inhibitor run's direction as "model"; they now show none, because O6's
  comparison has no mapping. Their class (비교 불가) was pre-committed and is unchanged.
- The genotype groups were an assumption at fixing. The B text later stated them
  (`lit-03d068babab3`), and they agree.

## 5. Comparison table (16 rows; every row counted)

Classes per model and reading are listed as M1 strict / M1 ordinal / M2 (strict = ordinal for
M2).

| Row | Q | Cells, intervention, time in text | Text direction | M1 strict | M1 ordinal | M2 |
|---|---|---|---|---|---|---|
| B01 | O1 pMEK | HCT116, SW480; MEKi; 24 h | increase | 미결정 | 부합 | **불일치** (no change) |
| B10 | O1 pMEK | Ras-mutated; AZD6244 time series | increase | 미결정 | 부합 | **불일치** (no change) |
| B03 | O1 pMEK | all lines; >20 µM | drop, not vs untreated | 비교 불가 | 비교 불가 | 비교 불가 |
| B08 | O1 pMEK | not named; AZD6244; within 1 h | increase | 비교 불가 | 비교 불가 | 비교 불가 |
| B13 | O1 pMEK | HEK Raf-ER + 4OHT | no strong increase | 비교 불가 | 비교 불가 | 비교 불가 |
| B14 | O1 pMEK | HEK Raf-ER + FGF | increase | 비교 불가 | 비교 불가 | 비교 불가 |
| B16 | O1 pMEK | Caco2 vector / wt B-Raf | increase | 비교 불가 | 비교 불가 | 비교 불가 |
| B02 | O2 pMEK | B-Raf-mutated; 24 h | no increase | 부합 | 부합 | 부합 |
| B09 | O2 pMEK | B-Raf-mutated; AZD6244 time series | no change | 부합 | 부합 | 부합 |
| B04 | O2 pMEK | all lines; >20 µM | drop, not vs untreated | 비교 불가 | 비교 불가 | 비교 불가 |
| B15 | O2 pMEK | Caco2 B-Raf V600E | no increase | 비교 불가 | 비교 불가 | 비교 불가 |
| B07 | O3 pERK | HT29, HCT116; U0126 | stated as purpose ("to abrogate"), not measured in text | 비교 불가 | 비교 불가 | 비교 불가 |
| B05 | O4 pRaf-1 | HCT116; U0126 24 h | decrease | 미결정 | 부합 | 부합 |
| B06 | O5 Ras-GTP | Ras-mutated; AZD6244 2 h | no increase | 부합 | 부합 | 부합 |
| B11 | O6 | Ras-mutated; + ActD/CHX | no change of the increase | 비교 불가 (pre-committed) | 비교 불가 | 비교 불가 |
| B12 | O6 | B-Raf-mutated; ActD/CHX | no influence | 비교 불가 (pre-committed) | 비교 불가 | 비교 불가 |

| Tally of 16 rows | 부합 | 불일치 | 미결정 | 비교 불가 |
|---|---|---|---|---|
| M1 strict (primary) | 3 | 0 | 3 | 10 |
| M1 ordinal | 6 | 0 | 0 | 10 |
| M2 strict | 4 | 2 | 0 | 10 |
| M2 ordinal | 4 | 2 | 0 | 10 |

**What the model computed** (`results.json`):
- **M1, KRAS untreated:** the loop RAF→pMEK→pERK⊣RAF oscillates. Repetition is a cycle of
  period 2 or 6, depending on the initial case; there is no fixed point.
- **M1, KRAS treated:** a fixed point with pMEK on, pERK off and pRaf1fb off. Per step and per
  case, pMEK is "increase" in 112 and "no_change" in 112 of the 224 case-steps; the strict
  reading is therefore undetermined.
- **Ordinal reading:** every case goes intermittent → always active (pMEK), so "increase".
- **BRAF, both models:** fixed points on both sides; pMEK no change, pERK and pRaf1fb decrease.
- **M2, KRAS:** fixed points; pMEK no change. KRASmut keeps RAS on, so a feedback on
  input-driven RAS has no effect.

**Rules each comparison rests on** (`results.json` → `rules`, both sides):
- pMEK, pERK: the RAS, RAF, MEK and ERK rules;
- pRaf-1: the same, plus R_FB;
- Ras-GTP: M1_R_RAS only (M1), or all four (M2).

## 6. Effect of the alternative assumption (feedback on RAS instead of RAF)

M2 is a sensitivity check. It was fixed with M1 and not tuned.

- It flips both scorable O1 rows (B01, B10) to **불일치**. In KRAS-mutant cells RAS is on
  regardless, so relief of a RAS-level feedback cannot raise pMEK.
- It removes the oscillation, so O4 (B05) becomes 부합 under the strict reading.
- O2 and O5 do not separate the two models: both say no change.
- M2 predicts a Ras-GTP increase in BRAF cells. No registered question asks this, and the text
  read has no such observation in these lines; the Lito abstract (C, melanoma) reports one.

So, among the questions that were scorable, only O1 (pMEK in KRAS-mutant cells) discriminates
the feedback site. The paper's own logic is the same (`lit-03d068babab3`, `lit-7bd2d4075c0e`).

## 7. What the model explains, and what it does not

**Explained**, in direction only and not independently of C:
- pMEK rises under MEK inhibition in KRAS-mutant lines, and not in BRAF-mutant lines. M1
  explains this only under the ordinal reading.
- Phospho-Raf-1 S289/S296/S301 is lost under U0126. M1 explains this under the ordinal reading
  only.
- Ras-GTP shows no increase in KRAS-mutant cells (both models).

**Not explained, or not comparable:**

| Item | Where it sits |
|---|---|
| M1's untreated KRAS state oscillates, but the paper reports pMEK "remains constant under vehicle control" (`lit-1fd73f7e342a`, an unregistered statement). The three strict 미결정 rows come from this. | **Representation**: synchronous Boolean update of a negative loop (rules + update scheme); the ordinal 부합 rests on a host assumption that intermittent = intermediate population level |
| Fold changes (six-fold HCT116, three- to four-fold SW480) | **Readout mapping**: Boolean; not comparable |
| pMEK drop above 20 µM in all lines | **Intervention mapping**: one MEKi level; it touches the assumption that the inhibitor does not block MEK phosphorylation, which the authors name as one possible cause |
| Rises within 1 h; Ras at 2 h; Raf-1 at 24 h | **Time**: not converted; the window is not a time |
| pERK under the inhibitor (O3) | **Data**: stated as the purpose of the treatment, not reported as a measurement in the text read (figures not read) |
| Cycloheximide / actinomycin D (O6) | **Model**: no translation or transcription node (pre-committed) |
| HEK Raf-ER and Caco2 inducible B-Raf, the paper's most direct feedback tests | **Scenario**: none fixed for these systems; adding them now would be after seeing B |
| Erk knockdown raises pMEK in KRAS lines, not in BRAF lines | **Intervention**: not registered; not scored |

**Size.**
- The ordinal reading needs every case path (`view: "full"`).
- Each comparison response was about 1.8 MB, measured from the structured content.
- A host reading the tool through MCP could not practically do this aggregation itself.

## 8. One next action

**Decide, benchmark-first, whether a window-aggregated readout belongs in `run_logic_model`.**

Before code, write benchmark questions:
- a negative loop;
- a fixed point;
- a mixed-by-case window;
- a not-computed window;
- the M1 KRAS case.

Each question asks what a host should be told when the paired direction changes from step to
step. The answer would be either:
- a declared aggregation (like the ordinal rule here) with its assumption carried in the
  output; or
- an explicit "oscillating; no single direction" status.

Reason:
- 3 of the 6 comparable rows in the primary reading depend on this.
- The only way to read them today is a host-side aggregation over 1.8 MB of case paths.
- This is a finding, not a fix: the engine is unchanged here.

## 9. Code, verification, host and cost

**Code.**
- The engine is unchanged. Product source changes: 0 lines.
- Base for this work: `3242cf7`; pre-registration commit: `d37c0b4`.
- `run.json` stamps the commit the outputs were computed at, and whether `src/` had uncommitted
  changes. It is re-stamped on the clean commit.

**Reproducibility.**
- `tests/integration/test_logic_biology_v1.py` re-runs `compute()` on `build_server()` and
  requires byte-identical `results.json` and `comparison.json`, and the same result twice.
- It also checks:
  - the pre-registration checksums, and the input hashes in `run.json`;
  - every rule's evidence id against the pre-registered source list;
  - that the alternative differs only in the RAS and RAF rules;
  - that each comparison differs only in `MEKi`;
  - every observation's span against the B reads, and against its absence from the
    pre-registration;
  - that every row is classified and counted;
  - the classification and both readings on synthetic inputs.

  No test requires agreement with the paper.

**Live host** (`host_check.json`):
- The R1 probe from review r2 returns `not_assessed` with a reason, and the host has
  `baseline_dependencies`, so the host runs the review-r2 code.
- A 3-step M1 replay gave the same model and run hashes and the same final state as the local
  run.
- The 24-step comparison runs were made locally only.

**Counts.** Measured, not estimated.

| What | Count |
|---|---|
| Searches | 4 of 6 allowed: 3 `research_evidence`, 1 PubMed search |
| PubMed metadata / full-text calls | 1 / 1 (full text came back empty) |
| `read_evidence_source` calls | 14 (10 before fixing; 4 results sections after) |
| Primary papers read in depth | 1 of 3 allowed (Fritsche-Guenther; 10 sections); two others by abstract only (their full text not available) |
| `run_logic_model` calls per `run_case.py` execution | 8 (4 comparisons in view full, 4 baseline-only); 0.98 s total; 7,538,751 bytes of structured content |
| `run_case.py` executions | 3, plus 2 × 8 calls per test run |
| Host `run_logic_model` calls | 2 (R1 probe; 3-step M1 replay of about 21 kB) |

Tokens and cost are not estimated.
