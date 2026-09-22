# The research path: open questions without a domain pack

## The problem this exists for

`ReasoningQuery` requires a `domain` and a `task`, and `ReasoningService.query` resolves a
`DomainPack` before anything else happens:

```python
pack = self.registry.resolve(request.domain, request.task)   # platform/service.py
```

That is right for what it does. A pack is a validated vocabulary with a verified verdict
behind it, and three of them exist. But it means a question nobody has written a pack for
gets `UnknownDomainError` where the bare model would have given an answer — so for exactly
the case where help is worth most, a new problem, the platform is **worse than no platform**
until someone spends a week writing a pack.

Adding a fourth pack does not fix this. Nor does routing everything to a "general" pack,
which is the same dispatch table with one more row and a worse verdict.

The goal is narrower and harder:

> Handle a research question **without writing domain code**, and improve a researcher's
> actual judgement over the same model given the same evidence.

The second half is the part that can fail, and it is not assumed. Until the A/B/C comparison
in P4 has run, nothing here claims the research path beats a plain answer.

## What it is not

The existing domain packs stay exactly as they are. They are the *optional specialist* for a
verified verdict, not a precondition for thinking about a new problem. The strict path's
behaviour — including its refusals — is unchanged, and a test asserts that an unknown domain
still raises rather than quietly falling through to exploratory prose.

## Shape

```
ResearchRequest ──> ResearchService.investigate ──> ResearchReport
  question                  │                          restated question
  goal                      │                          assumptions
  field_of_study (context)  │                          hypotheses  (evidence_linked |
  context {...}             │                                       unverified_candidate)
  constraints               │                          experiments (+ decision branches)
  evidence [labelled]       │                          open items
  budget                    │                          integrity findings
                            │                          provenance
                     ResearchBackend
                  (no silent fallback)
```

### Evidence keeps its label

Five things that are easy to conflate, kept apart by `EvidenceKind`:

| kind | means | locator |
|---|---|---|
| `user_observation` | the caller measured it; carries its measurement context | forbidden |
| `retrieved_source` | a span actually read from a document | **required** |
| `derived_inference` | reasoned from listed evidence; names which | forbidden |
| `model_prior` | the model proposed it with nothing behind it — a **search target** | forbidden |
| `predicted_outcome` | what an experiment is expected to show | forbidden |

Every item also carries a `content_hash`, filled automatically. Ids are stable across
sessions on purpose — that is what makes them citable — and the same stability would let a
silent edit pass unnoticed: `obs-1` saying "two-fold" and `obs-1` saying "ten-fold" compare
equal by id. The digest makes the change visible, and a supplied hash that disagrees with
the content is rejected outright.

The report carries an `evidence_snapshot` of everything it was offered, so a citation
resolves **inside the artifact**. A report holding only ids cannot be audited on its own.

`SourceLocator` is reused from `literature/contracts.py`, hash-verified, so "read from a
document" is a checkable claim rather than a style of sentence. A `model_prior` carrying a
locator is rejected outright: that is a guess wearing a citation.

**Nothing here is given an `EvidenceTier`.** A tier in this repository means a claim that was
argued for; a hypothesis proposed in an exploratory session does not earn one by arriving in
the same process.

### Two kinds of check, never merged

**Code checks** what code can: that a cited evidence id exists, that a hypothesis marked
`evidence_linked` cites something actually grounded, that an experiment says what any result
would change. These become `IntegrityFinding`s that travel *with* the report — they do not
fail the run, because "cites a nonexistent id" and "is bad science" are different questions
and only the first is decidable here.

**A person checks** whether the evidence supports the claim, whether a result from another
species was over-extended, whether the alternatives are the real ones, whether the experiment
separates anything. Keyword rules and the same model grading itself are not that.

### A missing provider is not an empty answer

`reasoning/llm.py`'s `get_backend()` returns a `TemplateBackend` when no API key is set. That
is right there — it can honestly hand back retrieved evidence. It is wrong here: there is no
honest offline answer to "design me an experiment", so a fallback would report a success that
never happened. `get_research_backend()` raises `BackendUnavailable` instead, and the CLI
gives it its own exit code (3) distinct from a bad request (1) and a provider that ran and
failed (4).

The exploratory system prompt is **separate**. `reasoning/llm.py`'s evidence-only prompt is
untouched and stays global for the strict path.

## Stages

### P0 — survey and baseline · **done**

Verified against the code rather than assumed: `domain`/`task` required and non-blank;
`registry.resolve` called before anything else; the LLM prompt evidence-only and global;
`get_backend()` silently falling back. Baseline at `e0d3335`: `verify.py` 9/9, 2103 passed.

### P1 — minimum working path · **done**

**Purpose.** A question with no domain reaches a real design, and the failure states are
honest.

**Files.** `src/virtualcell/research/{__init__,contracts,backend,service}.py` (new),
`src/virtualcell/cli.py` (one command added), `tests/unit/test_research_path.py` (new).

**Pass conditions.** A domainless question produces a report; two unrelated subjects take an
identical code path; evidence labels are enforced at the type level; unknown evidence ids,
overstated support and decision-free experiments are reported; a missing provider raises;
the strict path's refusals are unchanged.

**Limits.** Evidence is **injected**, not retrieved — no literature search, no knowledge
graph read, no writes. The offline tests use a scripted backend and establish that the path
works, **never** that the designs are good.

**Rollback.** Delete `src/virtualcell/research/`, revert the CLI hunk, delete the test file.
Nothing else imports it.

### P1.1 — review of P1 against its own claims · **done**

Six of seven review questions were checked by reading the code; three found real defects,
all fixed minimally:

| | finding | fix |
|---|---|---|
| model fabricating a source record | none — the model has no channel for an `EvidenceItem`, and `_assemble` builds none | test added to pin it |
| citations resolving to real evidence | ids were *checked* but never *resolved*; the report could not be audited alone | `evidence_snapshot` |
| same id, changed content | undetectable | `content_hash` |
| hypothesis promoted to fact | none — only `evidence_linked` / `unverified_candidate`, no `EvidenceTier` | — |
| format check vs scientific review | none — kept apart by construction and named as such | — |
| integrity errors shown only as success | **exit 0 regardless of findings** | exit `5` |
| provider limits, empty, malformed, truncated, budget | `max_model_calls` was declared and read by nothing; a `max_tokens` truncation was reported as a parse error | field removed (P3 adds it with the loop that spends it); `stop_reason` checked and named |

### P1.2 — review of P1.1, and the reply checked before it is used · **done**

Every defect below was reproduced first, through `ResearchService.investigate` and through
the CLI, against the code as shipped — in a separate worktree, so the reproduction could
not be contaminated by the fix. What is recorded is what was observed.

The report was assembled straight out of the model's payload, with coercion standing in for
validation. `investigate` now runs four steps in a fixed order — read the reply, **check the
reply**, assemble from what was checked, check the report — and the middle one was missing.

| | what could reach a reader | fix |
|---|---|---|
| a reply with no design | `{"restated_question": "R?"}` → 0 hypotheses, 0 experiments, **0 findings, exit 0** | `no_design_produced` / `design_withheld`, kept as two codes; no minimum count is imposed |
| malformed output | `null`, `[null]` and an unknown `support` escaped as raw `TypeError` / `AttributeError` / `ValueError`, past the CLI's typed handlers | `BackendCallFailed` naming the exact path |
| coercion inventing content | `"assumptions": "abc"` → `['a','b','c']`; an integer id → the string `"1"` | a string is not a list; no coercion after validation |
| a field nobody declared | `certainty: 0.99` and `citation: "Nature 2020"` **silently dropped, no trace** | `unexpected_model_field`, with the value quoted back |
| a reused id | two hypotheses called `H1`, both accepted, every citation ambiguous | `duplicate_hypothesis_id` / `duplicate_experiment_id` |

Declining to design is a legitimate answer, so none of this is made into a failure and no
minimum hypothesis or experiment count is required. A reply padded to a quota is worse than
a short one.

**The default text output hid what a reader most needs.** `--format text` is the default,
and it dropped `contradicting_evidence_ids`, `applicability`, `controls`, `measurements`,
`timepoints` and `priority_rationale`. `applicability` is the worst of those to lose: it is
where a hypothesis says its support came from another species — the over-extension warning,
printed nowhere. A design without its controls is not a design.

**The evidence digest did not cover the evidence.** It hashed the span's text and nothing
about where the span came from, so the same sentence from two different papers hashed
identically — measured, `59403c14a3a53de9` on both sides — and so did the same sentence read
from the Results and from the Discussion of one paper. Swapping one citation for another
left untouched the digest that exists to detect exactly that edit. Joining lists on `|` made
`["a|b"]` and `["a", "b"]` the same bytes. The locator now goes in whole, sorted-key JSON
replaces the joins, and `id` stays excluded so the same content under two ids still agrees.

**The provider's limits were the SDK's, not this repository's.** The Anthropic SDK defaults
to a ten-minute timeout and two retries, so what one request was allowed lived in a
dependency's release notes. Both are set here: 120s per request, 2 retries. `design()`
returns a `ModelReply`, and the report records what the provider reported: the model it
**served** (not only the one requested), `stop_reason`, and input and output tokens. A value
the provider does not report stays `None`; a zero would read as a measurement.

> **Correction.** An earlier version of this section said those two settings give "six
> minutes worst case", and the code and a test said the same. **That was wrong.** The
> timeout bounds a single HTTP request; the SDK sleeps between retries with backoff the
> timeout does not cover, so `timeout × attempts` is not an upper bound. And nothing here
> cancels a call that runs long, so **no total deadline is enforced at all** — the sentence
> described a control that does not exist. No 360-second ceiling is claimed. The settings
> are recorded as settings, and how long a call actually took is **measured** on a monotonic
> clock and reported as `elapsed_seconds`. Building an execution-deadline mechanism to make
> the old sentence true would be answering a documentation error with a subsystem.

`model_calls` and HTTP attempts are kept apart. The SDK retries inside one logical call and
never says how many attempts it made, so provenance carries `max_request_attempts` as the
**ceiling it ran under**, named as a limit, and no field claims a count nobody took.

**One run renders both ways.** The text form used to live inside the CLI command, so seeing
a report as text *and* as JSON meant invoking the command twice — two model calls, two bills,
and two different answers compared as though they were one. `render_report_text` is now a
function the CLI calls; anything holding a report can call it and get the same bytes.

### P2 — retrieval

Per-question literature search, spans read from documents, and a **read-only** path into the
existing knowledge graph. The check that matters: does absent or contradicting evidence
actually change the design, or does it only get appended?

Watch the existing literature orchestrator's ingestion side effects and keep the write
boundary separate — a research session's evidence does not belong in the permanent graph, and
a hypothesis generated here is never registered as established knowledge.

### P3 — the loop

Take a prior report plus new observations and update the judgement: what was kept, what
changed, what was withdrawn, and on what evidence. A past output is never treated as an
observation.

### Real-model status

**Not performed in the environment this was built in.** No `ANTHROPIC_API_KEY`, and the
`anthropic` package is not installed; the Claude-prefixed variables present are the Claude
Code harness's own session plumbing, not a general API credential this work is authorized to
spend. The CLI's refusal path was exercised and returns exit 3 with *"nothing ran"*.

So two things are true and must not be merged: **the path is verified to work** by contract
and integration tests over a scripted backend, and **no design it produces has ever been
judged**, because none has been produced by a model. The development cases, the B-condition
renderer and the rubric are committed and waiting.

P1.2 prepared the call rather than made it: explicit timeout and retry limits, and
provenance that records what the provider reported back. That is what a real run needs in
place beforehand so its cost and its answer can be attributed afterwards — it is not a run,
and `species_mismatch.json` stays excluded from any literature-based scoring until its
placeholder DOI is replaced by a span someone actually read.

### P4 — comparison

**A** the same model alone · **B** the same model given the same evidence · **C** the same
model, same evidence, through this path. Matched inference and retrieval budgets for B and C;
more calls for C is not an architectural win. Development cases ~8, independent cases ~12,
three runs each — a starting point to be adjusted and recorded before running, not a quota.

The ECM case is a **development** case. It has been discussed here, so it is not a holdout,
and calling it one later would be false. The sealed set and its rubric stay out of the
implementing agent's context, search and session memory; without that separation the result
is a development evaluation and holdout verification is recorded as not performed.

If C loses to B, isolate which step cost it — retrieval, context loss, claim review, design,
revision — and run the ablation that removes or simplifies that step. The rubric is not
adjusted to make C win.

### P5 — other surfaces

Connect the verified path to API/MCP. Same service, no second implementation. Optional
consultation of a domain pack only where its context genuinely applies. Permanent knowledge
adoption is a separate decision.

## Development cases

`tests/benchmarks/research/` holds five cases, the scoring rubric, and
`build_condition_b.py`, which renders a case as the **B** condition using the *same*
`build_prompt` that C sends — so B cannot accidentally be given a looser paraphrase of the
evidence than C receives, which would make any C advantage partly an artefact of
transcription.

Its README states in its first paragraph that these were written **after** P1, not before.

## Try it

```bash
virtualcell research --input request.json            # text
virtualcell research --input request.json --format json
```

Exit codes: `0` clean report · `1` bad request · `3` no provider (**nothing ran**) ·
`4` provider ran and failed · `5` report produced **with integrity findings**.

`5` exists so a script reading only the exit code cannot take "cites evidence that does not
exist" for an ordinary success. The report is still printed; the findings are information
about it, not a reason to withhold it.
