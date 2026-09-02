# Validation axes: closing the recommend → measure → interpret loop

The immortalization vertical told researchers to verify genomic stability and differentiation
capacity, and then could not read the answer back. Measure the thing it asked for, hand the
result in, and the report was byte-identical to never having measured it.

That is worse than not asking. A recommendation the platform cannot consume trains a user to
stop trusting the recommendations.

## The gap, as found

Reproduced by driving the product path, not by reading the code — see
`tests/unit/test_immortalization_validation_loop.py`.

### A. Differentiation retention — an axis that answers into a void

`adipogenic_retention` is a real typed input (`retained` / `lost` / `unknown`). Holding
everything else at a `possible_candidate` culture and varying only this axis:

| retention | status | flags | contradicting | `recommended_validation` | `next_experiment` |
|---|---|---|---|---|---|
| `retained` | `possible_candidate` | — | — | identical | identical |
| `lost` | `possible_candidate` | `functionality_compromised` | *"Adipogenic differentiation capacity is lost."* | **identical** | **identical** |
| `unknown` | `possible_candidate` | — | — | identical | identical |

The status invariance is correct and stays. The rest is the defect: **measuring the axis
cannot change the next action**, and `unknown` is indistinguishable from `retained` — an
unmeasured functionality axis reads as "nothing to check here".

### B. Genomic stability — not expressible at all

There is no typed axis. The generic escape hatch accepts anything:

```json
{"karyotype": "abnormal", "genomic_stability": "lost"}
```

and the values land in `measurements`, are echoed back in `derived_input.assessment_input`,
and reach nothing. No flag, no evidence claim, no risk, no missing-validation entry, no change
to the plan. The assessment path never mentions genomic stability at all — while the
*mechanism* path lists it as recommendation #1 for TERT+CDK4. The two halves of the same
vertical disagree about whether the axis matters.

In the graph, `phenotype:genomic_instability` exists as a node with **nothing pointing into
it**. It is reachable only as a next test to run (`sustained_proliferation
-SUGGESTS_NEXT_TEST-> assay:karyotype`), never as a state that was observed.

## The principle this must not violate

```
immortalization status  ≠  cell-line utility  ≠  genomic stability
```

Three orthogonal questions. All of these are coherent and must remain expressible:

- `possible_candidate` + `functionality_compromised`
- `possible_candidate` + `genomic_instability_detected`
- `possible_candidate` + both

So `CandidateStatus` is **not** redesigned. A validation axis reports beside the status, never
through it. The mistake to avoid is the tidy-looking one: letting an abnormal karyotype
"invalidate the candidate". It does not. The cells really are still proliferating; what
changed is what the line is good for.

## Two kinds of gap, kept apart

The vertical already had a notion of a missing measurement, and it means something narrower
than "unverified":

| | `missing_axes` | validation gap |
|---|---|---|
| question | can we *decide the status*? | is this candidate a **usable, stable line**? |
| members | the four senescence axes | genomic stability, differentiation retention |
| effect of a gap | status falls to `insufficient_evidence` | status unchanged |
| surfaced in | `missing_axes` | `recommended_validation` + `next_experiment` |

Merging them would be the easy move and the wrong one: an unmeasured karyotype would start
blocking a candidate call that the senescence and proliferation axes fully support. That is
why genomic stability and retention are **not** added to `_SENESCENCE_AXES`.

## The rule each axis follows

Three states, three different responses. The middle column is the one PR16 added; without it
a measurement changes nothing, and without the third column an adverse result reads as if the
platform never registered the answer.

| axis state | `recommended_validation` | `next_experiment` | flag / evidence |
|---|---|---|---|
| `unknown` | the gap | the assay that closes it | — |
| favourable (`stable` / `retained`) | **nothing** | **nothing** | measurement claim + a risk saying what it does *not* establish |
| adverse (`abnormal` / `lost`) | the *next* question | a follow-up, never the same assay | flag + measurement + interpretation + risk |

Concretely, an abnormal karyotype gets *"repeat karyotyping at a later passage to test whether
the abnormality is clonal and progressing"* — never *"run a karyotype"*. Lost differentiation
gets *"differentiation assay on an earlier-passage reference, to separate capacity lost in
culture from a protocol that never worked"*, because that is the question the loss actually
opened.

### One axis, not two

`genomic_stability` is the reasoning axis; karyotyping is the assay that measures it. Typing
both would create two authorities over one biological fact and admit
`karyotype=abnormal, genomic_stability=stable` with no rule for reconciling them. Which assay
produced a reading is provenance, not a second opinion.

`abnormal` deliberately does not say *how* abnormal. This vertical has no validated scale for
that, and an honest coarse label beats a number nobody can defend.

## Closing the loop opens the opposite failure

A measured axis must not read as a cleared one. Assertion fields (conclusion + evidence — the
kernel's `assertion_texts` scope, reused unchanged) are now checked against `safe cell line`,
`genetically safe`, `non-tumorigenic`, `validated for production`, `production-ready`,
`food safe`, `fully functional` and three variants. A violation raises
`ImmortalizationSafetyError` at build time rather than shipping.

Each favourable reading also carries its own explicit risk line, so the caveat is stated
rather than left to be inferred:

- stable → *"...does not establish a safe, non-tumorigenic or production-ready line; stability is a trend, and safety requires separate validation."*
- retained → *"...one axis of utility; it does not establish that the line is fully functional, production-ready or food-safe."*

## Graph closure

Both risk phenotypes existed as nodes with nothing pointing into them:

```
marker:karyotype                 -INDICATES-> phenotype:genomic_instability      (new)
marker:differentiation_capacity  -INDICATES-> phenotype:loss_of_differentiation  (new)
```

The edges hang on `marker:` nodes, not `assay:` nodes. An assay is what you *run*; a marker is
what it *reads*; only a reading can indicate a phenotype. `assay:karyotype` and
`marker:karyotype` therefore both exist and are not duplicates — the assay is the
`SUGGESTS_NEXT_TEST` target, the marker carries the `INDICATES` edge, matching how
`marker:gammaH2AX` already worked.

## Findings recorded, not fixed

**1. An assay node asserts a phenotype.** The pre-existing edge
`assay:differentiation -INDICATES-> phenotype:loss_of_differentiation` says that running a
differentiation assay implies loss of differentiation. It is the ontology error the new edges
avoid, it is pinned by `test_immortalization_seed.py`, and correcting it is its own change
with its own justification. Left in place, recorded here.

**2. No relation expresses "this assay produces this readout".** The vocabulary has
`SUGGESTS_NEXT_TEST` (gap → assay) and `INDICATES` (readout → phenotype) but nothing linking
an assay to the marker it yields, so `assay:karyotype` and `marker:karyotype` sit in the graph
unconnected. Inventing a relation for one PR would be worse than the gap.

**3. Measurement-consumption transparency — closed by PR17.** Resolved on the *envelope*
rather than in the `DecisionReport`: an unconsumed key still leaves the domain report
byte-identical (correct — nothing consumed it), and `ReasoningResponse.measurement_consumption`
now says so out loud. See [`measurement_consumption.md`](measurement_consumption.md). The
original finding read: The typed axis fixes the case that mattered, but
the generic `measurements` escape hatch is unchanged: an unrecognised key is accepted,
preserved, and reaches no reasoning, and **nothing in the response distinguishes a measurement
that was used from one that was ignored**. A caller who submits `telomere_length_kb` gets a
report byte-identical to not having submitted it. Pinned by
`test_an_unrecognised_measurement_key_is_preserved_and_silently_unconsumed` so a fix has to
come to that test and delete it. This is a platform-wide contract question, not an
immortalization one — it belongs in its own PR, alongside whether ingestion should reject or
report unknown keys.

**4. The assessment path uses no graph.** `build_decision_report` is fully deterministic and
never calls `explain`, so the new observation edges do not feed it. Grounding the assessment
path is a real question and a much larger one; the edges were added so the phenotypes are
*expressible*, which is a precondition for it rather than a substitute.

## Kernel

**Changes: none.** `missing_axes` and `ordered_unique` were sufficient, and the new work is
validation *policy* — which axes exist, what an answered axis means — which is domain
judgement and belongs in the pack. `validate_assertions` was reused unchanged for the
clearance-claim guard.
