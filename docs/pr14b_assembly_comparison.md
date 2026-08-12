# Assembly comparison: immortalization vs adipogenesis

The step the roadmap places between the minimal second vertical and PR14b. Its purpose is to
let the **comparison decide the abstraction**, not to let an abstraction justify itself
afterwards. It is a recorded reading; nothing is extracted here.

Sources read side by side:

- `src/virtualcell/agents/immortalization/rules.py` (`build_decision_report`), plus
  `baseline.py`, `effective_markers.py`, `trajectory.py`
- `src/virtualcell/agents/adipogenesis/assessment.py` (`assess`), plus `models.py` and
  `platform/packs/adipogenesis.py`

## Method

Each concern is split by four questions, because "the code looks similar" is not evidence:

- **A. Procedure** — would a different biology do the same *steps*? If yes, a shared
  primitive is possible.
- **B. Policy** — does a different biology give a different *answer*? Then it stays in the
  pack.
- **C. Vocabulary** — does the shared contract encode the first vertical's concepts?
- **D. Container vs reasoning** — both verticals filling the same *field* says nothing about
  whether the *content generation* is shared. `next_experiment` existing is a container;
  choosing which assay to run is biology.

## What each assembly actually populates

Measured, not assumed — one representative call each (immortalization with a trajectory
series and a conflicting-evidence intent added, to reach its conditional paths):

| field | immortalization | adipogenesis |
|---|---|---|
| `candidate_status` | set | **never** (not representable) |
| `flags` | set | **never** (not representable) |
| `supporting_evidence` | ✅ | ✅ |
| `contradicting_evidence` | ✅ | ✅ |
| `mechanistic_chain` | **empty in assessment** | ✅ every assessment |
| `uncertainty` | only from trajectory | **never** |
| `missing_axes` | ✅ | ✅ |
| `conflict_explanation` | only for one intent | **never** |
| `limitations` | **empty in assessment** | ✅ constant |
| `overinterpretation_risk` | ✅ conditional | ✅ constant |
| `recommended_validation` | ✅ conditional | ✅ constant |
| `next_experiment` | ✅ conditional | ✅ conditional |
| `trajectory` / `derived_input` / `input_conflicts` / `blocked_overrides` | ✅ | **never** |
| `cell_type_relevance` / `species_relevance` / `actionability` | **never** | **never** |

## Comparison matrix

| Concern | Immortalization | Adipogenesis | Shared procedure | Domain policy | First-domain residue | PR14b action |
|---|---|---|---|---|---|---|
| **status** | `baseline_status(markers) -> (CandidateStatus, flags)`; senescence wins, else proliferation + a measured senescence axis | `_status(data) -> (DifferentiationStatus, flags)`; program **and** lipid, else inhibited / not / insufficient | Only the *shape* `(status, flags)` — a 2-tuple, not a procedure | **All of it**: which markers, which thresholds, which verdict | **Yes** — `DecisionReport.candidate_status` is typed to `CandidateStatus` | **MOVE/GENERALIZE contract.** Keep derivation in domain |
| **flags** | `AssessmentFlag` (functionality_compromised, trend_needed) | `AdipogenesisFlag` (function_unmeasured, inhibitor_active, markers_incomplete) | None | Which conditions deserve a flag | **Yes** — `DecisionReport.flags` typed to `AssessmentFlag`, so adipogenesis cannot use it | **MOVE/GENERALIZE contract** |
| **supporting evidence** | per-marker `if` chain with bespoke sentences | loop over marker tuple with a templated sentence | "readings become established claims" — **already extracted** as `kernel.measurement_claim` | Which readings support, and every sentence | No | **KEEP.** Nothing new; PR14a already covers it |
| **contradicting evidence** | markers arguing against + missing-axis note + status-conditional | inhibitor note + expression-without-lipid note | None beyond "a list of claims" | Entirely — what counts as contradiction is biology | No | **KEEP IN DOMAIN** |
| **missing axes** | required senescence axes whose value is `UNKNOWN`, then relabelled | molecular markers unmeasured, plus the functional marker | **Yes** — `required − measured`, declared order preserved, "unknown" treated as unmeasured in both | Which axes are required, what counts as measured, display labels | No | **EXTRACT** (the one clear case) |
| **conflict explanation** | intent-gated; names only the markers that actually contribute | **absent** | None — exists in one vertical | Which marker pairs conflict | No | **KEEP.** Rule 1: one implementation is not a pattern |
| **uncertainty** | derived from trajectory state and terminal DT spike | **absent** | None — exists in one vertical | Trajectory semantics | Coupled to trajectory | **KEEP** |
| **limitations** | **not set by the assessment builder at all** (only by the mechanism/hypothesis catalog) | constant list on every report | None — the two do genuinely different things | The text | No | **KEEP.** See *unexpected findings* |
| **overinterpretation risk** | accumulated conditionally on status and flags | constant list | Conditional accumulation exists in one only | The text and the conditions | No | **KEEP** |
| **recommended validation** | conditional on missing axes, status, intent | constant single item | None meaningful | Which axis to verify | No | **KEEP** |
| **next experiment** | missing-axis→assay map + always-on telomere + status/intent conditionals, **hand-rolled de-duplication** | missing/status conditionals, no de-duplication needed yet | **Order-preserving de-duplication** of a suggestion list — real in one, latent in the other | Which assay answers which gap | No | **EXTRACT the de-duplication only**; the choice of assay stays domain |
| **mechanistic chain** | empty in the assessment path (grounded only in mechanism/hypothesis reports) | grounded on every assessment | `kernel.ground_links` — **already extracted** in PR14a | Which targets/relations are admissible | No | **KEEP.** See *unexpected findings* |
| **trajectory** | serialized `TrajectoryAssessment` | never | None — one vertical | Passage-series semantics | **Yes, conceptually** — the shape assumes a series pre-processing stage. But it is typed `dict[str, Any] \| None`, so it costs a second domain nothing | **LEAVE.** Smallest migration wins; moving it buys nothing today |
| **derived input** | which snapshot markers a derived trend replaced | never | None | — | Same as trajectory: conceptual, generically typed | **LEAVE** |
| **input conflicts** | snapshot vs series disagreement | never | None | — | Named for the trajectory mechanism, but generic `list[str]` | **LEAVE** |
| **blocked overrides** | derived trend withheld by a quality gate | never | None | — | Same | **LEAVE** |
| **cell type relevance** | never set | never set | — | — | No — not first-vertical residue | **LEAVE, but record**: unimplemented in *both* |
| **species relevance** | never set | never set | — | — | No | **LEAVE, record** |
| **actionability** | never set | never set | — | — | No | **LEAVE, record** |
| **conclusion** | `status -> text` lookup | `status -> text` lookup | A dict lookup; too thin to be worth a function | Every sentence | No | **KEEP** |

## The headline result

**The two assemblies share almost no procedure. What they share is a report *shape*.**

That is worth stating plainly, because it is the opposite of what a "shared decision
assembly" step assumes going in. Reading them side by side, nearly every concern is either
(a) content generation that is pure biology, or (b) a field both happen to fill. The genuinely
shared *steps* reduce to two small ones — computing which required axes went unmeasured, and
collecting an ordered suggestion list without repeats.

The real overlap is in the **contract**, not the code: both build a `DecisionReport`, and that
report carries the first vertical's status vocabulary.

So PR14b is small on the extraction side and focused on the contract. Manufacturing a larger
abstraction here would mean inventing shared structure the evidence does not show.

## Unexpected findings

Three things the hypothesis did not anticipate, all visible only by reading both:

1. **The immortalization *assessment* report sets no `limitations` at all.** Only its
   mechanism and hypothesis reports do, from the curated catalog. Adipogenesis sets them on
   every report. This is an asymmetry in the *first* vertical, not something to abstract — a
   candidate-status report that never states its limitations is arguably a gap, and it should
   be fixed as immortalization policy rather than smoothed over by a shared helper.
2. **The two verticals disagree about whether an assessment carries a mechanistic chain.**
   Immortalization grounds only in mechanism/hypothesis reports; adipogenesis grounds on every
   assessment. Neither is obviously wrong, but the shared contract silently permits both, so a
   consumer cannot tell "no mechanism found" from "this domain does not ground here".
3. **`cell_type_relevance`, `species_relevance` and `actionability` are dead in both.** After
   two verticals they still have no implementation anywhere. That makes them *speculative*
   fields rather than first-vertical residue — a different problem with a different fix
   (specify or delete), and one for whoever adds the third domain.

Two hypotheses were also **refined rather than confirmed**:

- `trajectory` / `derived_input` / `input_conflicts` / `blocked_overrides` were predicted to
  be residue. They *are* first-vertical concepts — but they are generically typed and optional,
  so they cost a second domain nothing. Residue that is free to ignore is not worth a
  migration; `candidate_status` is residue that actively blocks a second domain, and that is
  the difference that decides PR14b's scope.
- The "shared-core" list was predicted to be shared. It is shared **as containers only**. Not
  one of those fields has shared content-generating logic, which is exactly the
  container-vs-reasoning trap.

## Checkpoint decisions

### KEEP IN DOMAIN

status derivation, flag derivation, supporting/contradicting evidence selection and wording,
conflict explanation, uncertainty, limitations, overinterpretation risk, recommended
validation, choice of next assay, conclusion text, which mechanistic targets and relations are
admissible.

Reason: each gives a different answer for a different biology (question B), and several exist
in one vertical only (Rule 1).

### EXTRACT IN PR14b

1. **missing-axis assembly** — `required − measured`, order-preserving, one definition of
   "unmeasured". Present in both, identical procedure, different policy.
2. **ordered suggestion assembly** — order-preserving de-duplication for
   `recommended_validation` / `next_experiment`. Hand-rolled in immortalization today; a
   duplicate suggestion reads as emphasis nobody intended.

Both take policy as data and perform assembly only (Rule 3).

### MOVE / GENERALIZE CONTRACT

`candidate_status` and `flags` — the only residue that *blocks* a second domain rather than
merely sitting there unused.

Explicitly **not** moved: the trajectory quartet (free to ignore) and the relevance trio (a
different problem). Touching them would be a large schema rewrite driven by tidiness rather
than by anything either vertical needs.

## PR14b outcome

### Extracted

`reasoning/kernel/assembly.py` — `missing_axes` and `ordered_unique`, plus the `UNMEASURED`
convention. Both verticals call them; behaviour is unchanged in both. That is the whole
extraction, because it is the whole overlap.

### Contract: what was decided about the residue, and why nothing moved yet

`candidate_status` and `flags` are real residue — they carry immortalization's vocabulary in
a shared model, and adipogenesis cannot use either. Four migrations were considered:

| option | cost | verdict |
|---|---|---|
| **A** — remove status/flags from the report, keep them only on the platform `DecisionSupport` | touches the benchmark scorer, the CLI printer, the pack, the parity tests and every immortalization test | large, and the scorer reads `report.candidate_status` directly |
| **B** — retype as `status: str` | small | **loses the enum validation** that stops a typo becoming a status; explicitly a last resort |
| **C** — base report plus a domain extension | large schema rewrite | not justified by two verticals |
| **D** — add a domain-neutral verdict *beside* the existing fields | small and additive | leaves two representations of one thing — adding residue to fix residue |

None is worth doing **now**, and that is the finding rather than a deferral. The residue costs
adipogenesis nothing today: its verdict already reaches every caller through
`DecisionSupport.status`, which is domain-neutral and was general enough all along. A
migration would therefore be paid entirely in churn against the most safety-critical code in
the repository — the benchmark scorer and the immortalization report — to buy a tidiness no
caller is asking for.

The condition that changes this is a third domain, which the roadmap already sequences next.
At that point the residue stops being one vertical's leftover and becomes a pattern, and
option A becomes worth its cost — with `DecisionSupport` already proven as the destination by
two domains rather than one.

Recorded so the next person does not have to re-derive it: **the trigger is a third domain
needing an in-report verdict, not general discomfort with the field.**

### Deliberately untouched

The trajectory quartet (`trajectory`, `derived_input`, `input_conflicts`, `blocked_overrides`)
— first-vertical concepts, but generically typed and optional, so a second domain ignores them
for free. The relevance trio (`cell_type_relevance`, `species_relevance`, `actionability`) —
unimplemented in both verticals, a specification question rather than a residue question.
