# The adipogenesis vertical: scope, axes, and what it refuses to say

The second reasoning vertical, expanded from the minimal pack that existed to be a data point
for PR14b. Its purpose now is different: to show that a *complete* second biology can be built
on the PR14a/PR14b kernel **without the kernel learning any biology**. Kernel changes are
therefore not a goal here; they are a finding to be reported if one turns out to be
unavoidable.

## Gap analysis: what the minimal vertical had, and what was missing

**Already present and kept:** curated graph, deterministic status rule, mechanism report,
generic pack, API/CLI/service reach, kernel grounding, assertion safety, the
molecular-vs-functional distinction, missing-axis logic (via `kernel.missing_axes`).

**Declared but dead** — found by grepping the minimal vertical: `induction_days`, `species`
and `cell_type` were input fields nothing ever read. `induction_days` turned out to be the
single highest-value thing on the list (see *Time*, below).

| candidate | verdict | why |
|---|---|---|
| viability / stress interference | **added** | a dying culture does not differentiate, and reading "not differentiating" off a dying culture is a wrong conclusion with a completely different fix |
| conflicting evidence | **added** | lipid without the program is a real and common artifact (media loading), and it is neither differentiation nor its absence |
| molecular program completeness | **added** | the program has a temporal order; early-only is a distinct state with a distinct action |
| differentiation efficiency | **added** | 5% and 80% of cells differentiated are different results, and it is the number a cultured-fat programme actually cares about |
| time / induction day | **added** (as a modifier, not a series) | the same readings mean different things at day 2 and day 14 |
| morphology | **added**, corroborating only | real evidence, but never decisive on its own |
| maturation | **added as an axis, never as a status** | see *The maturity boundary* |
| recommended validation | **made conditional** | it was a constant list |
| next-experiment prioritisation | **added** | most-informative-first, so the list is a plan rather than a menu |
| assay quality / measurement confidence | **excluded** | PR13b's ingestion QC already owns acquisition quality; a second notion of it inside a vertical would be two authorities for one question |
| species / cell-type relevance | **excluded** | the report's relevance trio is unimplemented in *both* verticals — a specification question the comparison already flagged, not this PR's |
| passage trajectory | **excluded** | see *Time* |

## Scientific scope: the questions this vertical answers

1. **State** — is adipogenic differentiation under way?
2. **Evidence sufficiency** — can a call be made from what was measured?
3. **Failure mode** — did the program never start, or is it being actively held down?
4. **Functional confirmation** — is there lipid, not just transcript?
5. **Mechanism** — which adipogenic / anti-adipogenic pathways explain the state?
6. **Next experiment** — what measurement most reduces the current uncertainty?

## Axis model

Six axes. Each earns its place by changing a decision; none was added for completeness.

| axis | meaning | markers / assays | required | drives status | notes |
|---|---|---|---|---|---|
| **A. Early program** | commitment has been initiated | `PPARG`, `CEBPA` | ✅ | ✅ | the master regulators; without them nothing downstream means differentiation |
| **B. Late program** | the program ran to completion | `FABP4`, `ADIPOQ`, `PLIN1` | ✅ | ✅ | distinguishes *started* from *completed* |
| **C. Functional lipid** | the cell actually stores lipid | `lipid_accumulation`, `lipid_efficiency` | ✅ | ✅ | a marker panel is not a fat cell |
| **D. Inhibition** | something is actively holding the program down | `WNT_signalling`, `DLK1` | optional | ✅ | separates "did not start" from "was prevented" |
| **E. Viability** | the culture is healthy enough to be judged | `viability` | optional | **gates** | never produces a positive call; blocks a *negative* one |
| **F. Morphology** | rounded, droplet-bearing cells | `morphology` | optional | ❌ | corroborating; validation-only |

Values are coarse labels — `high` / `low` / `absent` / `unknown` — because a minimal-to-full
vertical has no validated quantitative scale, and an honest coarse label beats an invented
number. `unknown` and absent are the same thing: no reading.

## Status vocabulary

Five states. One was added; two that were considered were rejected.

| status | evidence | action it implies |
|---|---|---|
| `differentiating` | early **and** late program positive, lipid present | continue as planned |
| `partially_differentiated` | early positive, late not yet, lipid present or weak | **added** — extend induction; distinct from both neighbours |
| `not_differentiating` | program measured and negative, lipid absent, enough time elapsed | change the protocol |
| `differentiation_inhibited` | inhibitor active, early program not positive | address the inhibitory biology |
| `insufficient_evidence` | cannot tell — unmeasured, conflicting, or unhealthy | measure more, or fix the culture first |

**Rejected: `mature`.** Proving maturity from a marker panel is precisely the overclaim this
vertical forbids. Maturity is reported as an *axis* and a *validation recommendation*, never as
a verdict.

**Rejected: a distinct "culture compromised" status.** Low viability does not produce its own
verdict; it produces `insufficient_evidence` plus a flag, because the honest statement is "we
cannot judge this", not "this is a different biological state".

## Flags

`function_unmeasured`, `inhibitor_active`, `markers_incomplete` (kept), plus
`viability_compromised`, `conflicting_evidence`, `late_program_absent`, and
`maturation_unverified`. Flags never replace the status; they say what a reader must know
alongside it.

## Time: a modifier, not a trajectory

Adipogenesis has no passage trajectory, and the immortalization `trajectory` machinery is
**not** reused. Nor is a generic temporal-evidence structure introduced — PR14b deliberately
did not generalise the trajectory quartet, and inventing one here for a single consumer would
repeat the mistake that comparison step exists to prevent.

What is real is much smaller: **the same readings mean different things at different induction
days.** Absent late markers on day 2 is the expected course; on day 14 it is a failure. So
`induction_day` modifies interpretation — it gates the `not_differentiating` call and changes
the wording — and needs no temporal structure at all.

If a third domain also needs time-course evidence, *that* is when a generic structure is worth
designing, with two callers to shape it.

## Safety boundaries

Two claims this vertical must never assert, restated because expansion is exactly when they
erode:

- **lipid accumulation ≠ complete adipocyte maturity.** Storing lipid is what an adipocyte
  does; doing it does not make the cell finished.
- **adipogenic differentiation ≠ food safety.** Nothing here speaks to whether resulting cells
  are safe, edible, or fit for any downstream use.

Enforced by the kernel's assertion-scope check against a domain phrase list
(`mature adipocyte`, `fully differentiated`, `transdifferentiation`, `proves the cells are
fat`, `suitable for consumption`, `food safe`, `terminally differentiated`, `ready for
harvest`). The phrase list is domain policy; the *scope* it is checked against — conclusion
and evidence claims only, never the guidance fields that quote these phrases in order to
forbid them — is the kernel's.

## Kernel reuse

Used unchanged: `ground_links` + `targets_in` / `relations_in` / `all_of`, `missing_axes`,
`ordered_unique`, `measurement_claim` / `interpretation_claim`, `validate_assertions`.

**Kernel changes in this PR: none.** The one place expansion pressed on the boundary was the
conflict explanation — immortalization has one, adipogenesis now has one, and it is tempting
to call that a shared pattern. It is not: the two decide *which* readings conflict by entirely
different biology, and PR14b already recorded that container-sharing is not procedure-sharing.
Both build a `list[str]`; nothing else is common.

## Benchmark

`tests/benchmarks/adipogenesis_v0.{md,yaml}` + `eval_adipogenesis_v0.py`. Ten questions
through `AdipogenesisDomainPack.execute` — the product path, per the PR10b rule that a
benchmark scoring a private copy of the logic scores nothing. Hard axes (status, forbidden
phrases, required and forbidden flags) fail a question; soft axes (named gaps, a next step
that addresses the gap, stated limitations, maturity not assumed) only cost points, so a
report can be correct and still visibly weak.

Current: **10/10, all twelve points.**

Q3 and Q9 differ in exactly one reading — viability — and expect different verdicts. If that
difference ever stops changing the answer, the vertical is reading a dying culture as a
negative result, and no other test in the suite would notice.

## What building it revealed

1. **The distinction that took the most work was not scientific, it was epistemic.** Three
   of the four rewrites during implementation were the same mistake in different clothes:
   treating *"we did not look"* as *"we looked and it was not there."* An unmeasured
   completion panel became `partially_differentiated`; an unstated induction day became "too
   early to tell". Both make silence into evidence. The fix in each case narrowed the rule to
   require a *stated* reading, which is also why `induction_day` could stay optional.
2. **The benchmark's soft axes paid for themselves on the first run.** ADI-Q1 scored 11/12
   because ADIPOQ and PLIN1 being high suppressed `maturation_unverified` — which quietly
   says marker positivity verifies maturity. Nothing in this vertical measures adipocyte
   *function*, and only function could answer that, so the caveat is now unconditional on a
   positive call (and scoped to positive calls, where it was previously noise on negatives).
   No status assertion would have caught this: the label was right.
3. **Expansion did not need the abstractions PR14b declined to extract.** `candidate_status`
   and `flags` are still first-vertical residue on `DecisionReport`; the full vertical routes
   around them via `DecisionSupport` at no cost, exactly as PR14b predicted. The trajectory
   quartet was likewise not needed — time is a modifier here, not a series. The trigger for
   that migration remains the third domain, not this one.
4. **`provenance.pack` is a compatibility surface, not a description.** The expansion briefly
   renamed `PACK_ID` from `adipogenesis.minimal.v1` to `adipogenesis.v1` on the accurate
   grounds that the pack is no longer minimal — and that is beside the point. The string
   ships on every response, so anything already keying off it reads a rename as a *different
   pack*. It stays at `adipogenesis.minimal.v1`, pinned on the product path by
   `tests/integration/test_adipogenesis_provenance_pin.py`; renaming or versioning it is a
   provenance-policy change with its own migration, not a side effect of growing a domain.
