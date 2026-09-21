# External immortalization evaluation v1 — published cases the platform did not author

> Companion spec: `external_immortalization_v1.yaml` (machine-readable), harness:
> `eval_external_immortalization_v1.py`. **This is not an in-house scorecard and must never
> be reported as one.**

## Why this exists

The four in-house scorecards read 10/10 · 10/10 · 6/6 · 10/10. Every one of those questions,
its rubric, and the seed graph it runs against were written by this project. Benchmark-first
was followed — the questions preceded the implementation — but the author did not change.
What those scores establish is **internal consistency and regression safety**. They cannot
establish that the platform reasons correctly about biology, because nothing in them comes
from outside.

This evaluation's ground truth is what real cells did in real laboratories, as reported in
peer-reviewed papers with DOIs. The platform had no hand in producing it, and it can fail.

## Admissibility — what may enter this set

A case is admissible only if all of these hold. The rules were fixed before any score
existed; that is the whole point of writing them here rather than in the harness.

1. **Published, citable, primary.** A DOI, and a paper reporting its own experiment. Reviews
   are excluded: a review's summary of someone else's result is one more layer of authorship
   between the cells and the answer.
2. **A stated outcome.** The paper says what happened to the cells — immortalized, senesced,
   entered crisis, karyotype normal or aneuploid. "The construct was expressed" is not an
   outcome.
3. **Transcription only.** Every field in the encoding traces to a sentence of the paper,
   quoted in the YAML's `source_quote`. **Nothing is inferred.** An axis the paper does not
   report is `unknown`, even when a competent reader could guess it, and even when the guess
   would make the platform look better.
4. **The expected answer is the paper's, not the platform's.** It is derived from the
   reported outcome before the harness is run, never adjusted afterwards to match what came
   out.

Rule 3 is the one that costs something, and it is the one that makes the result mean
anything. See **Coverage** below for what it costs.

## The held-out boundary, stated honestly

Not everything here is unseen. The seed graph already encodes the mechanism that CDK4
functionally bypasses p16-mediated arrest, which is exactly what EXT-1's construct does. So
for that case the mechanism is **not** held out; what is held out is the **case outcome and
its marker panel** — whether the platform, shown what this paper measured, reaches what these
cells actually did.

Stating this narrows the claim. A reader who thinks this set proves the platform rediscovers
biology from scratch would be wrong, and would find that out here rather than from a
reviewer.

## Two numbers, because one would hide the other

**Fidelity** — of the arms the platform can represent, how many does it get right?

**Coverage** — how many of the reported facts could the input vocabulary carry at all?

Coverage is not the platform being *wrong*; it is the platform being *narrow*, and it is
invisible to every in-house scorecard, because an in-house question is written against the
vocabulary that exists. A real paper is not. Each arm lists what had to be dropped in
`unrepresentable`, with the reason.

Reporting fidelity alone would let a narrow platform score well by only ever being asked what
it can already say. That is the failure mode this whole evaluation exists to detect, so the
harness prints both and the summary is never a single number.

## Scoring

Per arm, three axes, each 0 or 1:

| Axis | Passes when |
|---|---|
| `status_match` | `candidate_status` equals the status the paper's outcome supports |
| `overcall_controlled` | the report does not present a possibility as a verdict, and raises an overinterpretation risk or limitation wherever the paper left a safety axis unmeasured |
| `species_caveat` | **non-bovine arms only** — the report says somewhere that the species or cell type differs from the vertical's intended context |

`species_caveat` is not scored on bovine arms; it would be free credit.

### The species axis is a foregone failure, and that is the measurement

`platform/packs/immortalization.py` declares `species` and `cell_type` as
`AxisKind.CONTEXT` — *"Recorded for provenance; no deterministic builder reads it."* The
platform therefore **cannot** emit a species caveat today, and every non-bovine arm here
scores 0 on that axis by construction.

This is not a trap. It is the gap between three things that should agree and do not:

- `immortalization_v0.md` §0 lists *"species/cell-type 적합성을 반영한다 (bovine primary ≠
  3T3-L1/human)"* as a scoring criterion of the benchmark philosophy;
- the pack declares that no rule reads species;
- the scorecard reads 10/10 — and **9 of its 10 questions are `species: bovine`**, the tenth
  states no species at all.

An axis every question holds constant cannot be scored by any of them. The in-house set was
structurally incapable of noticing, and it did not notice. That finding came out of trying to
*encode* these cases, before a single one was run.

The axis stays scored, at 0, rather than being quietly dropped. A rule written after seeing
the result is not a rule.

## When this evaluation fails

**A failing arm is a finding, not a bug to paper over.** The prohibited repairs, named so
they cannot be reached for absentmindedly:

- widening the seed graph until a case passes;
- inventing a marker value the paper did not report;
- relaxing an expected status after seeing the output;
- dropping an admitted case because it scores badly.

The permitted response is to record what failed and why, and to let a person decide whether
the platform changes. Where a failure traces to a genuine gap, it is written down in
`docs/` and pinned, in keeping with this repository's findings-over-fixes rule.

## Cases

Five papers, nine arms. Retrieved via PubMed; each is cited by DOI in the YAML.

| Arm | Paper | Reported outcome |
|---|---|---|
| `EXT-1` | Stout 2023, bovine satellite cells + bTERT/CDK4 | >120 doublings, myogenic differentiation retained |
| `EXT-2a` | Akimov 2005, human CD34+ · hTERT alone | **failed** — replicative capacity not prolonged beyond 4 months |
| `EXT-2b` | Akimov 2005 · HPV16 E6/E7 alone | permanent lines via crisis, **highly aneuploid** |
| `EXT-2c` | Akimov 2005 · E6/E7 + hTERT | >2 years, **near-diploid**, telomere length stabilized |
| `EXT-3a` | Liu 2025, Mongolian sheep fibroblast + hTERT | 36 passages, normal karyotype, soft agar negative, SA-β-gal reduced |
| `EXT-3b` | Liu 2025 · sheep TERT (sTERT) | as above, with greater effect than hTERT |
| `EXT-4a` | Zhang 2016, sheep fetal fibroblast · Tet-on hTERT **induced** | 250 days continuous culture, normal karyotype, no transformed phenotype |
| `EXT-4b` | Zhang 2016 · doxycycline **withdrawn** | reverts to normal proliferation, **senesces** after limited divisions |
| `EXT-5` | He 2015, pig fibroblast + pTERT | >40 generations, anchorage-dependent growth retained |

EXT-4 is the strongest arm pair in the set: the same cells, the switch removed, senescence
back. A negative control internal to one line is not something an in-house question can
fabricate honestly.

EXT-2 carries three outcomes from one paper, including the only arm where a telomerase-only
construct **failed** — while EXT-3 and EXT-5 are arms where a telomerase-only construct
worked. That contrast is the discrimination test; without it the set would only ever reward
saying yes.
