# Literature survey: what evidence establishes an immortalized line?

A distributional answer to a question a single paper cannot answer.

## Why this exists

The external evaluation (`../external_immortalization_v1.md`) scores the platform case by
case, and each case is bounded by whatever that one paper happened to measure. When every
positive case stalled on the same missing marker, the conclusion drawn — "the platform
requires something the literature does not report" — had n=1 behind it, repeated five
times. That is an anecdote with a sample size, not a finding.

The question is distributional: **across the field, what do authors actually present when
they claim to have established an immortalized line?** Answer that, and the platform's
required panel can be judged against evidence instead of against five convenience samples.

## Method

| | |
|---|---|
| Database | PubMed |
| Query | `immortalized[Title] AND (fibroblast OR myoblast OR "satellite cell" OR preadipocyte) AND (TERT OR telomerase) AND cell line` |
| Retrieved | 2026-09-22 |
| Corpus | top 50 of 93 hits, by relevance |
| Unit of observation | title + abstract + author keywords |

Each paper is scanned for *evidence classes* — kinds of support an author offers, not
individual assays. The patterns are in `assay_classes.py`, written out rather than hidden in
the script so any classification can be disputed on its merits.

## Files

- **`assay_classes.py`** — the evidence classes and their patterns, plus the three classes
  that make up the platform's positive-call gate.
- **`assay_hits.json`** — the committed result: per paper, its PMID, DOI, year, title and
  which classes matched. This is the artifact; everything else regenerates it.
- **`build_hits.py`** — rebuilds `assay_hits.json` from locally fetched abstracts.
- **`tally.py`** — prints the table. **Offline**: reads only `assay_hits.json`.

**Abstracts are deliberately not committed.** They are publisher-copyrighted, and a survey
does not need to redistribute fifty of them. The PMIDs are in `assay_hits.json` and the
query is above, so anyone can re-fetch and re-run — reproduction is a re-run, not a
rediscovery.

## Refreshing or widening the corpus

Fetch the PMIDs into a JSON list of `{pmid, doi, year, title, abstract, keywords}`, then:

```bash
python build_hits.py /path/to/corpus.json   # rewrites assay_hits.json, keeps `source`
python tally.py
```

Editing `source` in `assay_hits.json` by hand is how a changed query gets recorded; a
regenerated matrix keeps whatever is there, so update it in the same commit that changes the
search.

## Two limits, and what they do and do not affect

**Abstract-level reporting is a lower bound.** Methods sections carry more than abstracts
do, so every share here understates assay use. It is arguably still the right unit: a gate
decides what is *sufficient* to call something a candidate, and what an author puts in an
abstract is what that author considered sufficient to claim it. And a class at 0% is 0%
either way — a lower bound of zero is still zero.

**The corpus is not livestock-specific.** The query selects primary-cell immortalization by
telomerase across cell types, so it includes human trophoblast, endometrial, corneal and
mesenchymal lines alongside livestock fibroblasts. The *act* — establishing a line from
primary cells and arguing that you did — is common to all of them, but this is not a
bovine-specific distribution. Narrowing it is a one-line query change and a re-run.

## What this is not

It is not a rule, and nothing here changes platform behaviour. Deciding what a positive call
*should* require is a biological and editorial judgement about what this platform is willing
to call a candidate, and `CLAUDE.md` makes such a judgement a stop condition for an
unattended change. This is the material a person decides from.

Findings drawn from it: `../../../docs/external_evaluation_findings.md`.
