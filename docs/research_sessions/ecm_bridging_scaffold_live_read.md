# ECM bridging scaffold — first live use of `read_evidence_source` (2026-09-24)

A separate record. It does not rewrite `ecm_bridging_scaffold.md` (written from host PubMed reads
before this tool reached the host) or the baseline. The `host_supplied` items in that design keep
their label; nothing here relabels them.

Scope, as agreed: **one representative paper**, a short draft, no new experiments.

## Server and schema on the host

- The host restarted the `virtualcell` server on its own (new process, running the committed
  code); no process was killed and no configuration was changed.
- `read_evidence_source` is exposed on the host.
- **Schema, fresh context.** A subagent started with no knowledge of the field names and told
  not to read the repository saw full item schemas for `hypotheses`, `experiments` (with
  `branches`) and `evidence`: property names, `required`, `additionalProperties: false`, and the
  enums (`support`, `kind`, `verification`, `source_kind`). It built and submitted a draft from
  those alone. It took from the prompt only the top-level parameter names; every nested name
  (`support`, `discriminates`, `branches[].outcome/implication`, …) came from the schema, none
  was guessed, and no `unexpected_model_field` came back.
- **Schema, this conversation.** The host's already-loaded tool definitions in the original
  conversation were **not** refreshed: `check_research_draft` still showed bare `object` items
  and the old description. The draft below was therefore written from field names this context
  already knew — the limitation the fresh-context run exists to cover.

## The paper and what was actually read

Williamson et al., *JCI Insight* 2025 — "Active synthesis of type I collagen homotrimer in
Dupuytren's fibrosis is unaffected by anti-TNF-α treatment."
[DOI](https://doi.org/10.1172/jci.insight.175188) · PMID 40337865 · PMCID PMC12128996

| call | status | read range | `reached_end` | `next_offset` | new ids |
|---|---|---|---|---|---|
| `research_evidence` (issued in this server process) | literature `ok` | 400-char abstract prefix, truncated | — | — | `lit-36fa8d506553` |
| `read_evidence_source(part="abstract")` | `ok` | characters 0–1322 of 1322 | true | null | `lit-6123c0f21586` (first span), `lit-7a80e038c766` (the remainder, to 1322) |
| `read_evidence_source(part="full_text")` (listing) | `lookup_failed` | nothing | false | null | — |
| `read_evidence_source(part="full_text", section="Discussion")` | `lookup_failed` | nothing | false | null | — |

**The whole abstract was read. No section of the body was read through the server.** Nothing
here says what the Methods, Results or Discussion contain beyond what the earlier host PubMed
read recorded.

### Source text, source location, host description — kept apart

- **Source text** (`lit-6123c0f21586`, verbatim excerpt): "TNF-α reduced COL1A2 gene expression
  only in the presence of serum in 2D cell culture and had opposing effects on collagen protein
  production in the presence or absence of serum. TNF-α had only limited effects in 3D
  tendon-like constructs."
- **Source location**: abstract, PMC12128996; `source_kind: abstract`, `section_title: null`,
  `source_text_hash 70d3f05c…`.
- **Host description** (mine, not the paper's): under one cytokine, collagen gene expression and
  collagen protein responded differently depending on serum, in 2D; the effect was limited in 3D.

## What this span kept and changed in the design

| design decision | effect of this span | why |
|---|---|---|
| Serum as an explicit condition in E5 | **kept, on a narrower basis** | The abstract shows serum reversing the protein response to a cytokine in 2D. The earlier basis — the study's estimate of TGF-β in its serum — came from the Discussion, which the server could not read; the decision no longer leans on that number. |
| Gene expression is not a synthesis readout | **kept, weaker support than before** | The abstract shows expression and protein diverging under one treatment. The stronger statement (no positive relation between mRNA and chain ratios) is in the Results and remains `host_supplied`. |
| New collagen measured in construct **and** medium | **unchanged, not re-verified** | That rests on a Discussion passage (`host-dup-2`, `host_supplied`); the server's full-text read failed, so it was not re-read. |
| 2D precedent applied to a 3D scaffold | **caveat added** | The same span reports only limited effects in 3D constructs; a serum dependence seen in 2D may not carry over (hypothesis H2 below). |

## Draft checked on the live host

Question: whether E5 must run serum and defined low-serum arms. H1 (`evidence_linked` to
`lit-6123c0f21586`, applicability: TNF-α in 2D, not TGF-β1 in 3D) vs H2 (`unverified_candidate`:
the 2D serum dependence is small in 3D). Experiment E5a: TGF-β1 × medium, collagen protein measured
directly beside expression, with branches.

`check_research_draft` returned, read separately:

- `findings`: `[]` — a structural result only.
- `evidence_origins`: `lit-6123c0f21586` → `server_retrieved` ("Issued by this server and
  unchanged since"). This says the text is what the server read from the abstract. It does **not**
  raise its scientific weight: the span is still one study, in 2D, about a different cytokine.
- `scientific_validity_checked`: `false`.

The fresh-context subagent's own draft (no evidence cited, because it judged no read span to state
its hypotheses) returned one finding, `question_not_restated`, and empty `evidence_origins`.

## Two defects found by this use — recorded, not fixed here

1. **The Europe PMC full-text URL is wrong (existing provider).** `EuropePmcProvider.fetch_open_full_text`
   requests `…/rest/PMC/{pmcid}/fullTextXML`, which returns HTTP 404 for PMC12128996; the endpoint
   `…/rest/{pmcid}/fullTextXML` returns HTTP 200 with a 143 KB body for the same paper (two
   requests each, 2026-09-24). So every open-access body reads as "not openly available". This
   predates this PR and also affects the discovery agent's extraction path.
2. **`read_evidence_source` labels the provider's `None` as `lookup_failed`.** The provider uses
   `None` for "not openly available" (a 404). Once the URL is right, that case belongs in
   `not_available`; a real transport failure stays `lookup_failed`. While the URL is wrong,
   `lookup_failed` is the less misleading of the two, which is why it is recorded rather than
   flipped in isolation.

Neither was fixed in the change that recorded them. Both were fixed together in a later,
separately approved change (provider URL; status taken from the provider's contract). The
live re-read of this paper's body needs the host to load the fixed server; it is recorded as
its own section when it happens, not folded into the table above.

## Live re-read on the fixed server (2026-09-24, server started after `22e067d`)

Same paper, same host, a server process started at 05:23:14 UTC — after the fix commit (05:01:26).

| call | status | what it shows |
|---|---|---|
| `research_evidence` (issued in this process) | literature `ok` | `lit-36fa8d506553` — DOI 10.1172/jci.insight.175188, PMCID PMC12128996 |
| `read_evidence_source(part="full_text")` | `lookup_failed` | detail: "the body could not be parsed (XML DOCTYPE/ENTITY declarations are not allowed)" |

**What changed.** The fetch no longer ends at the 404: the provider now reaches the body, and a
body that will not parse is reported as `lookup_failed`, not as absence — the status split works
as intended. **What did not happen.** No section list came back, no Discussion span was read, and
no draft was checked against a server-read body passage. The decision "measure new collagen in
both construct and medium" is therefore **unchanged and still rests only on the earlier
`host_supplied` passage (`host-dup-2`)**; this run neither supports nor limits it.

**A third defect, found by this run — recorded, not fixed.** `literature/documents.py` refuses any
document containing a DOCTYPE declaration (`_FORBIDDEN_DECLARATION`). A real Europe PMC JATS body
begins with an external DOCTYPE — `<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal
Archiving and Interchange DTD with MathML3 v1.4 20241031//EN" "JATS-archivearticle1-4-mathml3.dtd">`
— and, in the body fetched for PMC12128996, no `<!ENTITY` declaration. So every real open-access
body is rejected at parse time, on this tool and on the discovery agent's extraction path; the
tests passed because their JATS fixtures carry no DOCTYPE. Changing what the parser accepts is a
safety decision (it exists to refuse entity expansion and external references) and was outside
the approval for this change.

The parser was changed afterwards under its own approval (external DOCTYPE without an internal
subset accepted and never followed; internal subsets, entity declarations, external references
and undefined entities still refused). The live read on a server carrying that change is
recorded in the next section when it happens.
