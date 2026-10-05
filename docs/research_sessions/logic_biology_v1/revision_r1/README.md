# Revision r1: separating what the model computes from what the experiment reads

r0 is unchanged and kept byte for byte (`../SHA256SUMS`, recorded at `346c1b6`):
- the pre-registration;
- the models;
- the observations;
- the results;
- the comparison and its classes.

r1 changes how r0 is **read**. It does not change what was computed, which classes the r0
classifier gave, or any rule, update scheme or intervention. It was written after the r0
comparison was known, so it is an interpretation, not a pre-registered evaluation.

Files:
- `fixed_points.py` → `fixed_points.json`: the fixed points of each model under each scenario.
- `row_semantics.json`: per row, the text's wording, what it states, the series, and the
  limit cause.
- `compare_r1.py` → `comparison_r1.json`: per row and column, the r0 class, the wording, the
  recorded direction, the computed window classes, the assumptions, and the r1 relation.

## 1. Why M1 has no steady state when untreated in KRAS cells

Inputs: KRASmut = 1, BRAFmut = 0, MEKi = 0. M1's rules then reduce to:

    RAS(next)  = GF OR KRASmut           = 1
    RAF(next)  = (RAS AND NOT pERK) OR 0 = NOT pERK      (once RAS = 1)
    pMEK(next) = RAF
    pERK(next) = pMEK AND NOT MEKi       = pMEK

At a fixed point every component equals its own rule: pERK = pMEK = RAF = NOT pERK. That has
no Boolean solution.

`fixed_points.json` confirms this on the product path. Of the 32 internal states, none is a
fixed point of M1 under `KRAS_control`. Every other model and scenario pair has exactly one.

What this does and does not say:
- **This combination of rules and inputs has no fixed point.** A fixed point is a state every
  rule maps to itself, so the set of fixed points is the same under every update scheme. The
  absence comes from the rules (the complete veto `NOT pERK`, KRAS always on, `MEKi` off). No
  change of update order alone can create one.
- **The cycles of period 2 and 6 are how the synchronous update runs these rules.** Another
  scheme would run them differently. No other scheme was run, and none is claimed: neither a
  fixed point nor any particular other behaviour.
- **r0 is narrowed here.** r0's README (section 7) put the oscillation down to "synchronous
  Boolean update of a negative loop (rules + update scheme)". The absence of a steady state is
  a property of the rules. Only the periodic path is the scheme's.
- **The text and the model do not meet here.** The text says pMek "remains constant under
  vehicle control" (`lit-1fd73f7e342a`). That is a statement about a measured population
  signal over time points. It is not an observation that no individual cell oscillates, and it
  is not read as one. How M1's logical path would show up in such a population measurement is
  not established in either direction. The path is not "contradicted by" the constant vehicle
  signal, and it is not "explained by averaging".

## 2. Text, recorded direction and computation, kept apart

r0 recorded B02 and B06 ("no increase") as `no_change`, with the limit in a note, and then
classified them as equal to the model's `no_change`. r1 keeps three things separate:
- **What the text states** (`stated`), in one of these forms:
  - increase;
  - decrease;
  - `no_change_observed`: a change was looked for and none was seen;
  - `no_increase`: only an increase is ruled out;
  - none.
- **The direction r0 recorded.** It is kept and not rewritten.
- **What the model computed.** This is the window classes on each side, for example
  `always_active -> always_active`, and the direction under the reading. A model `no_change`
  means the two Boolean states are equal. It is not a computed equality of measured levels.

**The r1 relations.** These are case-local, not a general scheme.

| Relation | Meaning |
|---|---|
| 일치 | The text states increase or decrease, the model gives the same, and nothing beyond the pre-registered identity readout is needed. |
| 조건부 양립 | The model's direction is consistent with the text only with a further assumption: an intermittent window as an intermediate level; two equal Boolean states as no measured change; or a text that rules out only an increase. |
| 불일치 (현 모형·판독 규칙 하) | Under the current model and readout rules the directions differ. This is not a refutation of the biological mechanism the model stands for. |
| 미결정 | The model's direction under the reading is undetermined. |
| 비교 제한 | r0's 비교 불가, with its cause kept. |

**Row by row.** r0 classes in brackets.

| Row | Wording | Stated | M1 strict | M1 ordinal | M2 (both readings) |
|---|---|---|---|---|---|
| B01 | "pMek levels rise sharply" | increase | 미결정 (미결정) | 조건부 양립 (부합) | 불일치* (불일치) |
| B10 | "phosphorylation of Mek increases" | increase | 미결정 (미결정) | 조건부 양립 (부합) | 불일치* (불일치) |
| B02 | "no increase in B-Raf-mutated cells" | no_increase | 조건부 양립 (부합) | 조건부 양립 (부합) | 조건부 양립 (부합) |
| B09 | "no change of Mek phosphorylation is observed" | no_change_observed | 조건부 양립 (부합) | 조건부 양립 (부합) | 조건부 양립 (부합) |
| B06 | "no increase of Ras activation" | no_increase | 조건부 양립 (부합) | 조건부 양립 (부합) | 조건부 양립 (부합) |
| B05 | "...but not in U0126-treated cells" | decrease | 미결정 (미결정) | 조건부 양립 (부합) | **일치** (부합) |

\* M2's 불일치 in B01 and B10 needs the assumption that two active Boolean states mean no
measured change. M2 computes pMEK active with and without the inhibitor
(`always_active -> always_active` in all 32 cases). That a measured pMek level would not rise
within the active state is an assumption, not a computation. The rows are 불일치 **under the
current model and identity readout**. They are not a refutation of feedback acting at RAS.

**Under the conditions they need:**
- B02, B06 and B09 are consistent with the model. None of them is an exact match: "no increase"
  is not read as no change, and is not read as a proven non-increase either.
- The only 일치 is B05 under M2. The change there is `always_active -> always_inactive` in every
  case, which needs nothing beyond the identity readout.

## 3. The ordinal reading: pre-registered, not validated

The ordinal rule was fixed before the results text was read. It is not a post-hoc adjustment.
Fixing it in advance does not validate its premise.

Three things are distinct:
- A logical path can change from step to step. A step is an update, not a time, so the
  fraction of active steps is not a fraction of time, a concentration or a probability.
- The 32 cases are the unknown initial states. They are not 32 cells, and not equally weighted
  members of a population.
- A cell population's measured level is neither of the above.

Every M1 ordinal agreement on a KRAS row (B01, B05, B10) rests on reading an intermittent window
as an intermediate measured level. These rows stay 조건부 양립 under that assumption. They do
not resolve the primary (strict) reading's 미결정. They are not promoted to a verified result.

## 4. What the counts are

The 16 rows are statements in the text, not independent experiments. Several share a series
(`comparison_r1.json` → `rows_by_series`):
- Fig 6B (24 h, MEK inhibitor): B01, B02, B03, B04.
- Fig 6D (AZD6244 ± ActD/CHX time series): B09, B10, B11, B12.

No row is removed as a duplicate.

r0's tallies are the output of the pre-registered classifier and are kept as such. Neither
those tallies nor r1's are hit rates of independent experiments, or a ranking of M1 against M2.

**"O1 discriminates M1 from M2"** (r0 README, section 6) holds only:
- under the assumption that KRAS-mutant RAS is always active (`OR KRASmut` in both RAS rules);
- under the complete-veto rules;
- under the identity readout, with "two active states = no measured change".

Under other readout or rule assumptions it need not discriminate.

**The ten rows r0 could not compare**, by cause (B03 and B04 carry two causes):

| Cause | Rows |
|---|---|
| Outside the model's scope (no transcription or translation node) | B11, B12 |
| No scenario or mapping (HEK Raf-ER, Caco2, a dose) | B03, B04, B13, B14, B15, B16 |
| Not secured in the spans read | B03, B04, B07, B08 |

The last cause is about the four results sections that were read, without figures. It does not
mean the paper has no measurement (for example, pERK under the inhibitor, or the cell line of
the 1 h series). No panel was searched to enlarge the denominator for r1.

## 5. The next development proposal, in two layers

r0 proposed deciding "whether a window-aggregated readout belongs in `run_logic_model`". That
merged two different things. They are separated here. Neither is implemented.

**A. A computed-path summary (output, product candidate).**
- **Input:** a reading window, and the readouts.
- **Output,** per readout, per side, per case:
  - always active;
  - always inactive;
  - varies along the path;
  - across cases: same or differs;
  - against the baseline: the set of paired directions that occur (e.g. {increase, no_change}),
    not one chosen direction;
  - any not-computed value, or exploration not complete.
- **Must keep:**
  - case labels, unweighted;
  - the pairing with the baseline;
  - "a step is not time";
  - whether a fixed point exists (section 1).
- **Must not:** turn a path or a case count into a level, a fraction or a probability.
- **Why:** reading this case needed every case path, about 1.8 MB per comparison; the summary
  is a few hundred bytes. This is an output-efficiency candidate, not a predictive improvement.

**B. A measurement model (a separate, biological question; not an engine feature).**
B is the declared assumption that maps A's summary to an assay. Examples:
- whether an intermittent path reads as an intermediate population level;
- whether two active states read as an unchanged signal.

Each mapping would have to be stated by a researcher, carried with its basis, and checked
against data. Building A does not supply B. Supplying B is not an improvement in prediction
until it is checked.

## 6. The one thing to check first for this case

**The measured pMek values behind Fig 6B and 6D for the KRAS-mutant lines,** read from the
paper's figures or source data, which were not read here:
- the untreated (vehicle) level;
- the inhibitor-treated level.

Both are needed against the assay's own range.

Two assumptions turn on this one measurement:
- whether "both active" (M2's 불일치) means anything;
- whether "intermittent = intermediate" (M1's ordinal 조건부 양립) means anything.

The value alone does not settle either. It is the measurement the readout mapping has to be
built on. No experiment is proposed.

## 7. Limits of this revision

- It was written with the r0 results in view.
- The `stated` labels and the series grouping are the host's reading of the spans.
- The figure panels are as named in the text; the figures were not read.
- Nothing was re-run except `fixed_points.py`, which uses 8 new single-step calls on
  `build_server()`.
