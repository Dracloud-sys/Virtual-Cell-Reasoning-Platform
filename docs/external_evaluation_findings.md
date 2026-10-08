# What nine published cases said that ten in-house questions could not

The four in-house scorecards read 10/10 · 10/10 · 6/6 · 10/10. The first external
evaluation — nine arms from five peer-reviewed papers, ground truth being what the cells
actually did — reads **2/9 on status, 9/9 on overcall control, 0/8 on species**, with **9
reported facts dropped** across 7 of 9 arms because the input vocabulary could not carry
them.

Both numbers are true at once, and the gap between them is the point. The in-house set
measures internal consistency and regression safety, which is what it was built for and what
it is good at. It cannot measure whether the platform reasons usefully about biology it did
not help write, because nothing in it comes from outside.

The protocol, admissibility rules and scoring were fixed in
`tests/benchmarks/external_immortalization_v1.md` **before** any score existed. Nothing below
was adjusted after seeing a result.

## First, a limit on these findings

Every encoding is **abstract-derived**. Each field traces to a quoted sentence of the paper's
abstract, and full texts were not read. A paper that does not mention a marker in its abstract
may well report it in a figure.

That matters most for Finding 1, whose whole force is "no paper reports γH2AX". Before anyone
acts on it, the five full texts should be checked. If γH2AX turns up in a methods section, the
finding weakens to "not reported prominently" — still something, but much less.

Stating this first because a finding whose limits arrive after the headline has already done
its damage.

**This limit fired, and it cost a case.** Full texts were sought for all five papers; only one
is retrievable (PMC holds no body for Akimov 2005 or He 2015, and Stout 2023 and Zhang 2016
have no PMC record). Reading the one available — Liu 2025,
[10.1080/10495398.2025.2459915](https://doi.org/10.1080/10495398.2025.2459915), retrieved via
PubMed — turned up two errors in **this project's own encoding** of EXT-3a/3b:

- **Doubling time is reported**, in a table the abstract does not mention, and it *worsens*
  monotonically across passages in both arms (hTERT 16.16 → 22.45 h; sTERT 9.81 → 18.61 h over
  P6→P36). The encoding recorded `DT_trend: unknown`.
- **The paper states the cells did not achieve complete immortalization**: *"only telomerase
  activity was activated, explaining the inability of Mongolian sheep fibroblasts to achieve
  complete immortalization"*, alongside *"a slow but inevitable aging process was observed"*.
  The encoding recorded `reported_outcome: immortalized`, read off the abstract's "effectively
  extends the lifespan".

Corrected, the input carries a worsening doubling time, which is a functional stress signal,
and the platform would return `senescence_or_stress_prone` — which is close to what the paper
actually describes. **So at least two of the seven "failures" were transcription error here,
not platform limitation.** Finding 1 survives on its own evidence (see below), but its arm
count does not. The disposition of EXT-3a/3b is open; see the last section.

## Finding 1 — the positive branch is unreachable from published characterization data

`agents/immortalization/baseline.py` gates `possible_candidate` on a three-way conjunction:

```python
proliferation_signal = (
    markers.get("PDL_trend") == "increasing"
    and markers.get("gammaH2AX") == "low"
    and markers.get("DT_trend") in ("stable", "improved")
)
```

**In a 50-paper corpus, γH2AX appears zero times.** Every arm whose paper reports a
successfully immortalized line returns `insufficient_evidence` — seven of nine.

The original form of this finding was weaker than it looked, and the correction matters more
than the conclusion. It read *"not one of the five papers reports γH2AX"* — which is n=1,
repeated five times. Each case was bounded by whatever that one paper happened to measure, so
"the platform requires something the literature does not report" was a guess wearing a sample
size. **One paper cannot establish what a field does.**

The question is distributional, and `tests/benchmarks/literature/` now answers it. Searching
PubMed for `immortalized[Title] AND (fibroblast OR myoblast OR "satellite cell" OR
preadipocyte) AND (TERT OR telomerase) AND cell line` (93 hits, top 50 by relevance,
2026-09-22) and tallying what each paper offers in support of its claim:

| evidence class | papers | share |
|---|---:|---:|
| marker / phenotype expression | 31 | 62% |
| passages / population doublings | 27 | 54% |
| differentiation capacity | 15 | 30% |
| morphology | 13 | 26% |
| karyotype / cytogenetics | 12 | 24% |
| growth curve / doubling time | 8 | 16% |
| p16 / p21 / p53 / Rb pathway | 8 | 16% |
| telomerase activity | 7 | 14% |
| telomere length | 7 | 14% |
| apoptosis | 5 | 10% |
| SA-β-gal / senescence stain | 4 | 8% |
| soft agar / anchorage / colony | 4 | 8% |
| tumorigenicity in vivo | 4 | 8% |
| **γH2AX (DNA damage)** | **0** | **0%** |

Verified against a regex artifact by raw search over the corpus: `H2AX` 0 occurrences,
`53BP1` 0. The scan works — `senescen` matches 47 times, `karyotyp` 14.

**The gate's three conditions are satisfied together by 0 of 50 papers.** Its two
non-γH2AX conditions are themselves uncommon in abstracts (PDL 54%, doubling time 16%), but
γH2AX is the one that makes the conjunction unreachable rather than merely demanding.

Measured rather than inferred, on EXT-3a (Liu 2025, sheep fibroblast + TERT):

| input | status |
|---|---|
| as the paper reports it (PDL increasing, SA-β-gal low, karyotype normal) | `insufficient_evidence` |
| + γH2AX low *(not reported)* | `insufficient_evidence` |
| + DT_trend stable *(not reported)* | `insufficient_evidence` |
| + both | `possible_candidate` |

EXT-5 (He 2015, pig fibroblast) already reports a stable doubling time, and is one marker
away: adding γH2AX alone flips it.

The asymmetry is what makes this sharp. SA-β-gal — the canonical senescence stain, and the one
these papers actually run — appears in `_SENESCENCE_AXES` and satisfies the *separate* "at
least one measured senescence axis" requirement. It **cannot substitute for γH2AX inside
`proliferation_signal`**. So a paper that ran the standard senescence assay, got a negative,
karyotyped the line, showed no anchorage-independent growth and passaged it 36 times still
cannot produce a positive call.

**This is not the platform being wrong about biology.** Refusing to call a candidate without a
DNA-damage reading is defensible caution, and the two arms the platform got right are both
negatives — it does not overcall. The finding is narrower and more useful: the required panel
was specified without reference to what published characterizations contain, and **no in-house
question could reveal that, because the in-house questions were written to supply exactly that
panel** (6 of 10 set `gammaH2AX` explicitly).

**Not fixed here.** Which markers should gate a positive call is a biological and editorial
judgement about what this platform is willing to call a candidate. `CLAUDE.md` makes such a
judgement a stop condition for an unattended change, and relaxing a gate until an external
case passes is the first repair `external_immortalization_v1.md` prohibits.

## Finding 2 — a scoring criterion no question could ever score

Three things that should agree, and do not:

- `tests/benchmarks/immortalization_v0.md` §0 lists *"species/cell-type 적합성을 반영한다
  (bovine primary ≠ 3T3-L1/human)"* as a criterion of the benchmark's scoring philosophy;
- `platform/packs/immortalization.py:212` declares `species` as `AxisKind.CONTEXT` —
  *"Recorded for provenance; no deterministic builder reads it"*;
- the scorecard reads 10/10, and **9 of its 10 questions are `species: bovine`**; the tenth
  names no species at all.

An axis every question holds constant cannot be scored by any of them. The platform's
declaration is honest and always was — this is not a hidden defect — but the benchmark claims
to score something the platform says it does not do, and the arrangement was structurally
incapable of surfacing the contradiction.

All eight non-bovine arms score 0 here, by construction rather than by accident. The axis is
kept and scored at 0 rather than dropped: a rule rewritten after seeing its result is not a
rule.

## Finding 3 — coverage: what the vocabulary could not carry

Nine reported facts dropped across seven arms. Grouped by cause:

**`ConstructType` covers two constructs and nothing else** (`TERT_only`, `TERT_plus_CDK4`,
`unknown`). It cannot express:

- HPV16 E6/E7 — oncogene-based immortalization (EXT-2b), or E6/E7 **plus** hTERT (EXT-2c);
- a Tet-on construct in its **off** state (EXT-4b), which is neither present nor absent;
- *whose* TERT. EXT-3's central finding is that sheep TERT outperforms human TERT in sheep
  cells; `TERT_only` flattens both arms to an identical encoding, so the paper's own
  comparison is invisible.

**The retention axis is hard-coded to one lineage.** EXT-1 is the flagship bovine cultured-meat
paper, and its functionality result is *myogenic* differentiation retained. The only field is
`adipogenic_retention`. For a muscle-cell product, the functionality axis that matters cannot
be entered at all, so the finding was dropped rather than mislabelled.

**`genomic_stability` is defined as the conclusion a karyotype supports.** EXT-5 reports
retained anchorage-dependent growth — real evidence against transformation, but not a
karyotype. Recording it as `stable` would promote a different assay's result, so it is
`unknown`.

Coverage is not the platform being wrong; it is the platform being narrow. It is invisible to
every in-house scorecard, because an in-house question is written against the vocabulary that
exists and a real paper is not.

## What held up

`overcall_controlled` scored **9/9**. Across every arm — including the two where the platform
had a wrong status — it never presented a possibility as a verdict, and it raised a limitation
or overinterpretation risk wherever a paper had left a safety axis unmeasured.

Both negative arms were correct, including **EXT-4b**, the strongest case in the set: the same
sheep line as EXT-4a with the inducible construct switched off, senescing after limited
divisions. The platform reached `senescence_or_stress_prone` from a PDL plateau alone, with no
senescence marker available to it.

A platform that is cautious, refuses to overcall, and errs toward `insufficient_evidence` is a
defensible thing to be. The question Finding 1 raises is whether the threshold for leaving that
state was set against real data or against the questions it was going to be asked.

## What the gate edit changed, and what it did not

The γH2AX privilege is gone. `proliferation_signal` now asks for at least one senescence axis
measured and reading **low while none reads high**, rather than naming γH2AX; and an
*unreported* doubling time no longer blocks a call, while a *worsening* one still does.

Two results, and the second is the more interesting one.

**The external evaluation moved: `status_match` 2/9 → 4/9.** EXT-3a and EXT-3b are now
correct — though that is the corrected encoding doing the work as much as the gate.

**All four in-house scorecards are byte-identical, per question.** A material change to the
positive-call gate left 10/10 · 10/10 · 6/6 · 10/10 completely unmoved. That is the thesis of
this whole exercise stated as a measurement: the in-house set cannot see a change to the one
rule that decides whether anything is ever called a candidate.

One thing it *could* see, and did. The first cut of the change cleared the gate on "some axis
reads low", and **IMM-Q10 caught it** — that question is deliberately contradictory (γH2AX
high, p21 high, SA-β-gal low) and a single clean reading was outvoting two that screamed
senescence. Generalizing which marker counts must not become letting a caller cherry-pick.
The in-house suite is a regression net, it did its job here, and nothing above is an argument
for retiring it.

### The remaining five failures have one cause

EXT-1, EXT-2b, EXT-2c, EXT-4a and EXT-5 still return `insufficient_evidence`. Every one of
them reports **no senescence axis at all** — no SA-β-gal, p16, p21 or γH2AX. What they report
is passages, karyotype, morphology, anchorage dependence and differentiation.

Which is what the survey says the field reports: passages/PDL 54%, differentiation 30%,
morphology 26%, karyotype 24% — against SA-β-gal at 8%. **Requiring a senescence axis at all
is still requiring something 92% of these papers do not publish.**

The obvious next move is to let a normal karyotype contribute to a positive call. It would
flip EXT-2c and EXT-4a immediately. It is **not** done here, because it is a larger judgement
than the one authorized: `genomic_stability` is currently declared orthogonal — *"instability
does not stop the cells proliferating, so it cannot retract a call the proliferation axes
support"* — and making stability *support* a call reverses that axis's declared role rather
than widening a panel. That is a decision about what this vertical means by its own model,
and it belongs to a person.

## Two open domain questions

**EXT-3a/3b's encoding was wrong; the correction is applied, and how it was authorized is
part of the record.** `DT_trend` is restored to `worsening` (required by admissibility rule 3
— it puts back what the paper reports). `expected_status` and `reported_outcome` are changed
to the non-candidate branch, which is a different kind of act: revising an expected answer
*after* a score existed, in the direction that raises fidelity, is the first thing the
protocol prohibits an unattended run from doing. It was put to a person and authorized
explicitly rather than folded in quietly. The basis is the paper's own Discussion, quoted in
the spec.

**EXT-2a's expected status is disputed, and is recorded as disputed rather than settled.**
Akimov 2005 reports a clear negative — hTERT alone did not prolong replicative capacity — but
measured no senescence marker. "Growth arrest, cause unmeasured" has no distinct value in a
three-way vocabulary. It is scored against `senescence_or_stress_prone` because the paper's
finding is a negative result rather than an absence of data; a reader who would score it
`insufficient_evidence` is making a defensible different call.

This one is a person's to settle, not an unattended run's. It is the only expected answer in
the set that was not read directly off a paper when it was written.
