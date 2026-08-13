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
