# Provenance at the traversal boundary: what closed, and what is a decision for a person

`explain` boosts a target's confidence when several paths reach it. PR #30 made that boost
require **edge-disjoint** paths, and recorded its own limit in the same breath:

> Edge-disjointness is a proxy for independence, not independence itself. Two distinct edges
> drawn from the same paper are still not independent evidence, and this cannot detect it:
> `Interaction` carries `evidence: list[str]`, but the traversal `Edge` in
> `knowledge/store.py` carries only `relation`, `target_id`, `confidence`, `forward`.
> Provenance is stored and then dropped at the traversal boundary.

This document records what closing that gap actually required, because the obvious reading —
"pass the `evidence` field through" — is wrong in a way that would have been expensive to
discover from the scorecards.

## The finding: provenance was one type holding two kinds of thing

Every connector already populates `Interaction.evidence`. Surveying them:

| Producer | Strings written |
|---|---|
| `knowledge/sources/reactome.py` | `reactome:IEA` (or bare `reactome`) |
| `knowledge/sources/intact.py` | `intact` |
| `knowledge/sources/uniprot.py` | `uniprot` |
| `knowledge/sources/sample.py` | `curated:sample` |
| `knowledge/sources/immortalization_seed.py` | `curated:immortalization_seed`, plus prose rationales and one study citation |
| `knowledge/sources/adipogenesis_seed.py` | `curated:adipogenesis_seed` |
| `knowledge/sources/genome_editing_seed.py` | `curated:genome_editing_seed`, plus a prose caveat |
| `literature/resolution.py` | `review_status:…`, `resolution:exact_name_match`, `lit_marker:<id>`, `curated:<id>` |
| `literature/ingestion.py` | `review_status:…`, `run:<id>`, `article:<key>`, `source_hash:<…>`, `verified:<…>` |

Two kinds are mixed:

- **Source-level** — `reactome:IEA`, `intact`, `uniprot`, `curated:immortalization_seed`,
  `review_status:pending_review`. *Every* edge from one connector carries the identical
  token.
- **Study-level** — `article:<key>`, `run:<id>`, `source_hash:<…>`. These name one document.

A naive rule ("two paths sharing an evidence string are not independent") would have been a
regression dressed as a fix: every immortalization seed edge shares
`curated:immortalization_seed`, so the entire curated graph would collapse into a single fact
and corroboration would disappear from every scorecard at once. **A source is not a study.**

The opposite heuristic — a downstream parser that knows `article:` is study-level and
`reactome:` is not — fails differently and more quietly: a connector added later invents a
prefix the parser has never seen and silently opts out of the rule. That is the same class of
defect as the one being fixed, with a longer fuse.

## What shipped

Provenance is **typed at the point it is created**, not classified downstream.

- `Interaction.study_id: str | None` — the single study an edge was read from. `None` is the
  honest answer for a curated table distilled from many sources, and it is the answer every
  connector but one gives today.
- `Edge` carries `evidence` and `study_id` through verbatim. Nothing is derived or defaulted
  on the way; an edge with no recorded study reports none.
- `explain` admits a path only while it shares neither an edge nor a study with an
  already-admitted one. `None` contributes no constraint, so the curated graph behaves exactly
  as it did — which is why every scorecard's per-question scores are unchanged.
- `MechanisticLink.provenance` reports the distinct provenance strings behind the route it
  reports, so the confidence can be traced to its support.

`literature/ingestion.py` is the only site that sets `study_id` today, because it is the only
site that knows one. That is not a gap to fill by guessing: giving a seed table a synthetic
study id would assert that its rows are one reading, which is false.

## Open: per-edge evidence tier — a decision for a person

`Edge` now carries provenance, and the **tier** still ignores it. A link's tier comes from hop
count and relation strength alone, so a hand-curated mechanistic edge and a weak literature
association at the same distance are graded identically.

Closing this means answering, per connector, questions like:

- Is a Reactome `IEA` (inferred from electronic annotation) edge `established`, or
  `hypothesis`? The evidence code is already captured and discarded.
- Is an IntAct physical interaction `established` regardless of detection method, or does the
  method decide?
- Does a curated seed row inherit `established` from having been curated, and if so, does the
  one seed row carrying `hypothesis; Believer Meats, Nature Food 2025` become an exception in
  data or in code?
- Does `review_status:pending_review` cap a tier, and at what?

These are biological and editorial judgements about what the platform is willing to call an
established fact. `CLAUDE.md` makes such a judgement a stop condition for an unattended
change, and the alternative — inventing a tier table per connector so a test goes green — is
precisely the kernel-bent-to-fit-its-caller failure that rule exists to prevent.

The gap is asserted rather than described, by
`test_evidence_tier_is_still_derived_from_shape_alone_not_from_provenance` in
`tests/unit/test_explain_study_independence.py`. Closing it will fail that test loudly and on
purpose.

## Also open: independence is still a lower bound

Two studies can share authors, a cohort, a cell line, or a reagent lot. `study_id` cannot see
any of that, so paths from two papers are treated as independent when they may not be. The
selection remains a *floor* on corroboration in both senses: greedy rather than maximal, and
blind to dependence above the document level. Under-counting is the safe direction, and it is
the direction taken.
