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

## Who reasons: the plugin split

The delivery shape is **a host LLM with VCRP plugged into it as an MCP server**, not VCRP
calling a model of its own. That decides the division of labour, and it is close to the
opposite of the one P1 was built under:

| | does |
|---|---|
| **the host LLM** | understands the question, proposes competing hypotheses, designs the experiment, weighs the meaning, writes the explanation |
| **VCRP** | looks evidence up, walks mechanism paths, checks sources and structure, reports which registered domains declare anything matching |
| **the researcher** | makes the research judgement, approves the experiment |

So `research_evidence` and `check_research_draft` **call no model and need no API key**. That
is not a limitation being worked around; it is what the split means. The internal backend and
the B/C runner stay as an optional path — nothing on the MCP route imports them — and a real
provider run is no longer a precondition for anything here.

What gets reused rather than rebuilt: the evidence contracts, `SourceLocator` and its hash,
`content_hash`, `check_integrity` unchanged, the literature run statuses, and `explain`.

### Two tools on the existing server

Registered in `virtualcell/mcp/server.py` beside `list_domains` / `describe_domain` /
`reason`, which are unchanged. A second server would double what a host must configure and
split the guidance a model reads in two, for what is two more tools.

**`research_evidence(question, context, search_literature, max_graph_seeds)`** — no domain
required. Returns, in this order: what ran, what it does not establish, then the material.

* `lookups[]` separates four outcomes that an empty list would merge: `ok`, `no_matches` (it
  ran, found nothing), `lookup_failed` (it did not complete — absence means nothing here),
  `not_requested`, `not_implemented`. The literature statuses come from
  `DiscoveryRunStatus`, which already tells a zero-result search from a provider error and
  from a timeout.
* `evidence[]` is `EvidenceItem`s built only from records that actually carry text. A record
  with no abstract is a reference, not a span someone read, and inventing a statement for it
  would be the fabricated citation the contracts exist to refuse.
* `graph_findings[]` is **not** evidence — see the finding below.
* `domain_overlap[]` lists **every** registered domain, with `uninformative_matches` naming
  the axes every domain declares. A filtered list reads as a recommendation, and matching
  `cell_type` — which all three declare — made every domain look equally applicable to a
  scaffold-degradation question.
* Discovery only: extraction, verification, conversion and ingestion are all opt-ins on the
  literature agent and none is passed. Nothing reaches the permanent graph, and a test
  asserts the serialised store is byte-identical across a lookup.

**`check_research_draft(...)`** — runs `check_integrity` over a draft the host wrote. None of
what that checks depends on who wrote it. The result leads with what it did **not** do:
`scientific_validity_checked` is always `false` and `not_checked` lists the six things a
clean `findings` list does not mean. Provenance records `authored_by: host_llm` with
`model_calls: 0`, because filing a host's design under an internal provider run would
misattribute the reasoning.

Evidence origin is **verified, not trusted**: each submitted item is matched against what
this server actually issued, by id *and* `content_hash`, giving `server_retrieved`,
`server_retrieved_but_modified` or `host_supplied`.

### Two defects found by driving the tools

**The graph lookup could never hit.** `KnowledgeStore.search` substring-matches the *whole*
query string, so passing an entire question can only match an entity whose text contains that
sentence. `search("Does telomerase activity change senescence?")` returns `[]` while
`search("telomerase")` returns `TERT`. The lookup reported `no_matches` permanently and
looked like it had run. It now tokenises, and each finding carries the `matched_term` that
found its seed so a reader can see how thin the connection is.

**Every domain "matched" the question.** See `uninformative_matches` above.

### Finding: a graph hit has no evidence label

`EvidenceKind` has five values and none means *read from this platform's knowledge graph*. A
traversal is not a document span, not the caller's observation, not an inference from session
evidence, not a model's prior and not a prediction. Widening the enum to fit its third caller
on first contact is how a vocabulary stops meaning anything, so `GraphFinding` is its own
record type and this is recorded rather than fixed inside the milestone that found it.

Whether the right answer is a sixth kind, a separate contract, or leaving graph results
outside the evidence vocabulary entirely is a decision for whoever has seen how hosts
actually use them.

### Connecting it to a Claude Code host

`.mcp.json` at the repository root registers the stdio server as a project MCP server. A
host reads it **at session start**, so nothing about it takes effect in a session that is
already running.

```jsonc
{ "mcpServers": { "virtualcell": {
    "command": "${VCRP_PYTHON}",
    "args": ["-m", "virtualcell.mcp", "--literature"]
} } }
```

`${VCRP_PYTHON}` rather than a path: an absolute path is wrong on every machine but one,
and a relative path assumes the host spawns with the repository as its working directory.
Neither belongs in a committed file.

**Two values the user sets in the environment settings** (cloud environment menu in the
session title bar → Edit). Neither can be set from inside a session, and both apply to
**new** sessions only:

| field | value |
|---|---|
| **Setup script** | `bash scripts/setup_mcp_env.sh` |
| **Environment variable** `VCRP_PYTHON` | the absolute path the script prints — in this container `/home/user/Virtual-Cell-Reasoning-Platform/.venv-mcp/bin/python` |

The setup script builds that interpreter: guarded `python3.12` discovery, `uv` when
present, `.[mcp]` installed, idempotent. Measured 3.5 s cold, 1.0 s warm, so running it on
every session start is cheap. `.[llm]` is **not** installed and no API key is needed — these
tools call no model.

Confirm the path rather than trusting it: `bash scripts/setup_mcp_env.sh` prints it, and the
venv self-ignores so it never appears in `git status`.

**Start the new session on this branch, not `main`.** `.mcp.json` and the setup script live
on `feat/research-path`; a session started from `main` has neither.

### A failed lookup is not a search that found nothing

Measured against the live API, and it is the difference between "nobody has studied this"
and "we did not manage to look":

| | body | stability |
|---|---|---|
| genuine zero hits | `{"version":"6.9","hitCount":0,"request":{…},"resultList":{"result":[]}}` — 192 B | 6 of 6 |
| incomplete response | `{"version":"6.9"}` — 17 B, HTTP 200, identical headers | 3–4 of 10, **for any query**, including one with 43,683 hits |

`data.get("resultList", {})` turned the second into an empty result list, so the run was
recorded `zero_results` and reached a host as *"The search ran and returned no articles for
this query"* — on a subject with tens of thousands of papers. Under-reporting a failure as an
absence is the direction nobody recovers from, because nobody looks again.

`_page` now checks the envelope's presence on every page, and a missing **or mistyped**
field is enough: no `hitCount`, a null/string/bool `hitCount` (`bool` is a subclass of `int`,
so `True` would otherwise have passed as zero hits), no `resultList`, no `result` field, or a
null `result`. Three cases stay apart — an incomplete envelope is a failure wherever it
lands; an empty result list *inside* a valid envelope is how pagination ends; a malformed row
inside a valid list is still skipped with a warning.

It routes through the path that already existed: `ProviderError` → `PROVIDER_ERROR` →
`lookup_failed`. No new provider, no new status, and **no retry** — a retry would hide how
often this happens, which is the thing a caller needs to know.

Six live calls after the fix, every outcome recorded:

```
collagen scaffold degradation      #1 [ok]            23 evidence
collagen scaffold degradation      #2 [ok]            23 evidence
fibroblast stiffness myofibroblast #1 [lookup_failed]  no usable hitCount
fibroblast stiffness myofibroblast #2 [lookup_failed]  provider_timeout after 10.0s
zzqqxx_no_such_term_98765          #1 [no_matches]     ran and returned no articles
zzqqxx_no_such_term_98765          #2 [no_matches]     ran and returned no articles
```

The `curl` reproduction is recorded as evidence that this is not a quirk of the Python
transport. It is **not** evidence about the origin server: every request here goes through the
same proxy, so where the response is produced is not something these measurements establish.

### The literature switch

`--literature`, or `VIRTUALCELL_MCP_LITERATURE=1`, is what wires the searcher in. The
committed `.mcp.json` above passes it; omit it to run the graph and the draft check with no
outbound network at all.

**Enabling it searches nothing on its own**: it wires the existing Europe PMC discovery
agent in, constructing it performs no I/O, and a request still has to pass
`search_literature=true` before anything leaves the machine. No new provider, no model call.

Without the flag, `search_literature=true` answers `not_implemented` — which is honest, and
was previously the *only* possible answer from the shipped config.

### Four defects in the first version, reproduced through the tools

**The startup path could never search.** `main()` called `build_server()` with no arguments,
so `literature_agent` was always `None`. The tool was reachable and the capability was not,
and no configuration could change it. Fixed by the flag above — and because the MCP package
is forbidden by an AST test from importing `virtualcell.agents`, the wiring lives in
`virtualcell/composition.py` rather than in the adapter. Widening the test would have been
one line and would have removed the only thing keeping that boundary true.

**The annotation said the opposite of the truth.** `open_world_hint` was hard-coded `false`
while the tool could reach the public internet. Hosts use annotations to decide what needs
confirming. It is now `true` exactly when a searcher is wired in.

**The draft adapter re-introduced the coercion defects P1.2 had already fixed.** Measured on
the shipped tool: `"discriminates": "H1"` became `["H", "1"]` and produced two bogus
`unknown_hypothesis_id` findings — a defect report the adapter invented, about hypotheses the
host never wrote. An integer evidence id became `"1"`, an id nobody supplied. A hypothesis
carrying `certainty: 0.99` and `citation: "Nature 2020"` had both silently dropped, so a host
that attached a fabricated citation was told its draft checked out clean.

Fixed by **reusing** `validate_report_payload` (made public for this) rather than cloning it.
Every check in it is about the payload, not about who wrote it, and it imposes no minimum
number of hypotheses or experiments.

**Repeated searches collided on one evidence id.** Every search numbered from `lit-1`, so the
first hit of a second search took the first hit of the first search's id with different text,
and the ledger's hash was overwritten — after which the **unedited** first item came back
classified `server_retrieved_but_modified`. A fabrication warning about material the server
itself had handed over. Ids are now derived from the content hash, so they collide only when
the content is genuinely the same, and the ledger's first write wins.

### Usability of what comes back

* **Short names survive tokenisation.** A flat four-character floor dropped `ECM`, `p53`,
  `p16` and `Rb` — the names this field is mostly made of. A short token now earns its place
  by mixing letters and digits or by being a capitalised symbol; a bare `60` does not.
* **`context` is not a search filter, and the status says so.** It was accepted and passed to
  the searcher as `{}`. Mapping it onto `LiteratureQuery`'s species/cell-type/gene fields is
  real work with its own vocabulary questions; claiming it happened would be cheaper and
  false.
* **A truncated span is reported beside the evidence, not marked inside it.** `" [...]"` used
  to be appended to `source_text`, so the span no longer matched the document it claimed to
  come from and its hash covered a display artefact. `truncated_evidence_ids` carries the cut.
* **Graph findings are out of scope for the draft check**, and `not_checked` says so —
  including that re-submitting one as a `user_observation` or `retrieved_source` to get it
  checked would make an unverified traversal look like something someone read.

### What has and has not been exercised

Three different things, kept apart:

| | |
|---|---|
| **protocol** | done — `initialize` / `list_tools` / `call_tool` over a real `ClientSession`, not `server.call_tool`, which skips the wire |
| **real public literature lookup** | **not performed** — every search in tests and records uses a stub, so nothing here has queried Europe PMC |
| **use with a real host LLM** | **not performed** — nothing here has been driven by a host |

The tools running is not a host using them well, and connecting a tool is not evidence that
anyone's reasoning improved. That needs a new research question, real tool calls, and a look
at what the host designed and what it changed after the check.

**To try it:** start with `--literature`, then ask the host a question with no registered
domain — *"For an ECM scaffold bridging a dermal defect, does degradation outpace collagen
deposition, and does that drive myofibroblast conversion? Use the virtualcell tools."* Watch
whether it calls `research_evidence` before designing, whether it relays `lookups` and
`limits`, whether it cites returned ids rather than papers it names itself, and what
`check_research_draft` changes about its answer.

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

### The run bundle, and what it can and cannot show

`tests/benchmarks/research/run/` is the deliverable for an environment with no credential:
a bundle someone authorised runs unchanged. Nothing runs without `--spend-approved`.

Two defects in its first version were reproduced through the runner and fixed:

* **A reply that arrived and then failed checking left nothing on disk.** `c_raw.txt` and
  `c_call.json` were written only after `investigate` returned, so a reply the provider had
  produced and billed for vanished behind an error message. They are now written the instant
  the reply arrives, before the JSON is parsed. If no reply ever arrives, neither file is
  written — an invented raw text or a guessed token count is worse than the gap.
* **The run returned `0` whatever happened.** It now uses `virtualcell research`'s own codes:
  `0` clean · `1` bad usage · `3` no provider (nothing ran) · `4` a call failed · `5` findings.
  The manifest is rewritten after every entry, and each run gets its own folder — a non-empty
  `--out` is refused rather than cleared, because those are outputs somebody paid for.

**What the comparison measures**: a system prompt, a required output structure, and a
post-hoc check, against a plain answer from the same model on the same material. It is **not**
a test of automated literature search (P2 does not exist), **not** a test of knowledge-graph
reasoning, and **not** a measure of factual accuracy against the literature.

**Every observation in every case is invented for development.** A `user_observation` is an
input in the shape a caller's observation would take; the label says what the model is being
handed, not that anyone performed the measurement. And a case containing no
`retrieved_source` means no invented paper is in its *input* — it does **not** mean a model
cannot fabricate a citation in the free text it writes.

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
