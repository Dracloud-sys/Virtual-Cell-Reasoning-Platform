# draft_v2 revision notes

Script: `revise_v2.py` (loads `draft_v1.json`, writes `draft_v2.json`).

## (a) Changes made, by finding group

**1. `unsupported_evidence_link` — kind `input`, field `hypotheses[].supporting_evidence_ids`,
case `supports_link_not_in_supporting_ids`, 5 occurrences (H2, H3, H4, H5, H6).**

For each flagged hypothesis the field was absent while `evidence_links` already named
`role: "supports"` entries for it. Filled in from those links only, in draft order, deduped,
restricted to evidence ids whose `evidence[].kind` is `retrieved_source` or `user_observation`
(all 14 are `retrieved_source`). No id was invented and no `method`, `scope_limit` or
`contradicts` link was promoted:

- H2 → lit-13f07d427fef, lit-90bac4ae80b3, lit-91332fe8e2a5
- H3 → lit-8ccc91bd45f9, lit-d4c2a13f46ee
- H4 → lit-4003fcca2815, lit-13f07d427fef, lit-21c2cde4f3dc, lit-de72b3cfc53c, lit-31f9da012da1
- H5 → lit-b1bf272184af, lit-b0c020392ab5, lit-87a281f303a5, lit-086e187e2c2d
- H6 → lit-e62f54ed4087, lit-90bac4ae80b3

Each set matches the ids the result itself listed for that hypothesis.

**2. `unknown_hypothesis_id` — kind `input`, field `experiments[].discriminates`, 39
occurrences across E1–E6.** Every entry was a pair string ("H1 vs H2"). The schema says
`discriminates` takes one hypothesis id per entry. Each pair was split into its two ids and
the per-experiment list deduped, preserving first-appearance order. The set of hypotheses each
experiment is declared to separate is unchanged; only the encoding changed. All resulting
values are ids in `hypotheses[]`.

**3. `assumption_without_stated_assumptions` — kind `review`, 3 occurrences. One fixed.**
`E4:H1:GATA6_protein` (basis `assumption`, no assumptions) was given the assumption text the
draft already states in the sibling prediction `E4:H1:aSMA_on_substrate` — same hypothesis,
same experiment, same soft-gel-at-d5 readout logic (a carried-ligand effect being indifferent
to substrate is exactly what makes both readouts `no_change` there). Text copied verbatim; no
new scientific claim written.

## (b) Left unchanged deliberately

- `E2:H1:aSMA_in_naive_recipient` (conditioned-medium transfer, no blocker) — **unresolved.**
  The assumption it would need (about carryover ligand in transferred donor medium) is not
  stated anywhere in the draft for this hypothesis and readout; the two nearby H1 assumptions
  concern antibody access and plate-bound ligand reaching co-cultured cells, which are
  different logic. Inventing one would be a new scientific assumption.
- `E3:H1:clonal_bimodality` — **unresolved.** The sibling E3 assumption ("fresh plastic plus
  an acid wash removes most adsorbed and surface-bound ligand") backs a *decrease* in aSMA
  after replating; an *absent* bimodality claim rests on uniformity of an extracellular ligand
  effect, which the draft does not state. Left alone.
- H1, H7, H8 `supporting_evidence_ids` — not flagged (they are `unverified_candidate`), so
  untouched even though H7/H8 have `supports` links.
- All biology: statements, `support` values, `expected`/`condition`/`versus`, `basis`,
  `evidence`, `evidence_links` roles, `mechanism_links`, designs, controls, `what_if`.
  Verified programmatically: with the three edited field families stripped, v1 and v2 are
  identical, and `what_if` is byte-equal.
- No `view` key added.

## (c) Information needed beyond the schema and the result

None. The schema's `discriminates` description states the required shape and names the
`unknown_hypothesis_id` code; its `supporting_evidence_ids` description states that
`evidence_links` is not read in place of the field and that `evidence_linked` needs at least
one `user_observation`/`retrieved_source` id. The result named the exact hypotheses and the
exact ids. The only judgement call was rule 3 (which of the three review items has its
assumption already stated in the draft); that is a reading of the draft, not a guess about
field meaning. Nothing was looked up outside these three files.

## (d) Result bytes actually needed

`check_v1_compact.json` is ~38 KB. The input problems live in `finding_groups` — the three
group headers plus their occurrence lists, roughly 6–7 KB. `not_computed` (~1 KB) confirmed the
`discriminates` consequence. The remaining ~30 KB (`evidence_origins` for 17 ids, `not_checked`,
`plan_summary`, `omitted`) was not needed to locate or fix anything; I read the group summaries
and skimmed the rest programmatically rather than in full.
