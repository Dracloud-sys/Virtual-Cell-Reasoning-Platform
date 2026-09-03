# The genome-editing vertical

The third domain, chosen for the shape of its decision rather than its subject — see
[`third_domain_selection.md`](third_domain_selection.md). It answers *does this clone carry the
edit I intended, and can I use it?*

It also completes a coherent workflow rather than adding a random vertical: **immortalize the
line → edit it → differentiate it**, three stages with three different decision shapes.

## What makes it a real test of the kernel

The other two verticals read a value and ask what it means. This one must know **how the value
was measured** before it can say what it means:

```
PCR band                 ->  a band is not a genotype
Sanger / NGS + alleles   ->  a genotype
```

A negative from PCR is weak evidence of absence; a negative from sequencing is a finding.
Neither existing vertical has any notion that evidence strength varies by instrument.

That asymmetry is easy to get half-right, so it is pinned in both directions: a PCR-positive
reaches no verdict, and so does a PCR-negative.

## Status vocabulary

| status | meaning |
|---|---|
| `edited_clonal` | edit present, sequenced, single allele pattern |
| `edited_mosaic` | edit present, sequenced, mixed population |
| `unedited` | sequenced against a matched control and absent |
| `insufficient_evidence` | conflict, no control, a weak assay, or no allele call |

Two are **deliberately absent**, and they are the safety boundary:

- no `functional_knockout` — a confirmed DNA edit says nothing about whether the protein is
  gone. Every positive call carries `function_unverified` so "edited" is never read as "off".
- no `off_target_free` — three clean predicted sites are not a clean genome, and no assay this
  domain models can establish an absence across one. `off_target_unassessed` is cleared only by
  a genome-wide search.

## Axes

| kind | axes |
|---|---|
| status | `edit_detected`, `edit_assay`, `parental_control` (required); `allele_pattern`, `sequence_confirmed` |
| guidance | `off_target_screened`, `protein_expression`, `edit_type` |
| context | `species`, `cell_type`, `target_gene` |

`allele_pattern` decides clonal from mosaic and is deliberately **not required**: it is only
answerable once an edit was found, so requiring it would report a false gap on every genuinely
unedited clone. That is the same *"we did not look"* versus *"we looked and it was not there"*
distinction the other two verticals protect, in a third guise.

## Decision order

Blocking conditions first, because each says the readings cannot be trusted rather than
describing what the locus contains:

1. the screen and the confirmation disagree → `insufficient_evidence` + `conflicting_evidence`
2. no matched parental control → `insufficient_evidence` + `control_missing`
3. the assay cannot read an allele → `insufficient_evidence` + `weak_assay`
4. then, and only then, the locus result decides.

## Graph

21 nodes / 22 edges, entirely disjoint from both existing seed graphs — a third domain that
entangled with the first would be a weaker generality test, not a stronger one.

The domain's headline rule is carried by the **relation vocabulary** rather than asserted in
prose: `marker:allele_sequence -INDICATES-> frameshift`, but
`marker:amplicon_size -ASSOCIATED_WITH-> knock_in_integration`. A band and a genotype are
different strengths of evidence and the graph says so. The `marker:` / `assay:` split follows
the PR16 ontology rule — an assay is what you run, a marker is what it reads, and only a
reading can indicate a phenotype.

## Benchmark

`tests/benchmarks/genome_editing_v0.{yaml}` + `eval_genome_editing_v0.py`, ten questions
through `GenomeEditingDomainPack.execute`. **10/10.**

Written before the implementation, and two questions changed the design: the conflict scenario
forced a separate `sequence_confirmed` axis rather than two competing assay fields, and GE-Q3
forced the assay-strength rule to run in both directions instead of only against a positive.

## Findings

**1. `DecisionReport.candidate_status` is still immortalization's.** A third domain hits the
same wall the second did and routes around it the same way, via `DecisionSupport.status`. PR14b
deferred migrating this on the grounds that the trigger would be a third domain. The third
domain is here — and it was **not blocked**, only inconvenienced, so the finding is recorded
rather than acted on. Three callers routing around a field is now the evidence a migration
would need.

**2. `missing_information` is not always round-trippable as an axis name.** Immortalization
reports `SA-b-Gal` for an axis a caller must send as `SA_b_gal`. An agent that echoes what is
missing back as an experiment key gets `unsupported` — precisely the loop an MCP client runs.
Not fixed here because the same label appears inside an existing evidence claim, and this
milestone must not change claim text.

**3. Adipogenesis does not enum-validate its marker axes.** Its description is therefore a
stronger promise than its model enforces: `PPARG: "hgih"` is accepted and silently treated as
no reading. Immortalization and genome editing both refuse an invalid value at the boundary.
Recorded rather than fixed: tightening it changes a shipped vertical's behaviour.

**4. No abstraction gap in the kernel.** The third domain needed nothing the kernel did not
already provide — `ground_links` / `targets_in` / `relations_in` / `all_of`, `missing_axes`,
`ordered_unique`, the claim tier conventions and `validate_assertions` all applied unchanged to
a domain none of them were written for. Kernel changes: **zero**.
