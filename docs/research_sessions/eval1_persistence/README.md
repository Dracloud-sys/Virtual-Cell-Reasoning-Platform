# Eval 1: a competent general answer vs a VCRP-assisted answer, and the check's input/output burden

Two parts, recorded separately because they answer different questions.

1. **The comparison (2026-10-02, base `621bf3d`).** On one unseen question, a structured general
   answer (A) and a VCRP-assisted answer (B) were written in separate subagent contexts from the same
   frozen evidence pack. Conclusion: B's scientific judgement was not clearly better than A's. VCRP
   added limited value: three predictions resting on an unstated assumption, and the dependence of
   the central reading on one source (`what_if`). B cost about 5× the tokens, and most of its first
   check was input-format noise.
2. **The follow-up (this change).** The same analysis, made usable with fewer revisions and a
   shorter reply. No new check, no new biology, no change to predicted values, evidence tiers or
   judgement rules.

Same model as writer and evaluator, same session. **Not an independent evaluation and not a
holdout**: the question, the evidence and the evaluation items were chosen in this session.

## Records (`records/`, checksums in `records/SHA256SUMS`)

Byte-for-byte copies of the session files. The originals are not overwritten by any revision.

| File | What it is |
|---|---|
| `evidence_pack.md` | Question, development assumptions (not user-confirmed), sources S1–S8 with the span ids read, and what the pack does not contain |
| `evaluation_items.md` | The 8 items, frozen before either answer existed |
| `condition_A_answer_attempt1.md`, `condition_A_draft_attempt1.md` | A's first attempt, **stopped by a safety classifier mid-answer**; incomplete, kept as a record |
| `condition_A_answer.md`, `condition_A_review_note.md` | A, retried in a fresh context with the same prompt; complete |
| `condition_B_payload_1.json`, `condition_B_check_1.json` | B's first draft as sent to the host's `check_research_draft`, and the host's reply (83 findings) |
| `condition_B_payload_2.json`, `condition_B_check_2.json` | B's revised draft and reply (1 finding) |
| `condition_B_answer.md`, `condition_B_review_note.md` | B's final answer and notes |

The evidence spans are abstract text as returned by the platform's reader, the same kind of
material stored in `plan_cases/`. No full text, user data or credentials are included.

## Usage

Reported by the harness per subagent, as totals. **Input, output, cache and tool-response
volume are not separated in what the harness reports**, so they are not split here. Tokens are
not billing.

| Run | Tokens | Tool calls | Wall time | Note |
|---|---|---|---|---|
| A, attempt 1 | ~62k | 4 | ~97 s | stopped by the safety classifier; incomplete |
| A, retry | ~74k | 6 | ~225 s | complete |
| B | ~386k | 49 | ~2,462 s | includes search, reading, two checks, and analysing ~300 KB replies with scripts |
| Usability trial (part 2) | 74,265 | 10 | 144 s | one revision from the compact reply; the subagent reports one of its messages was cut by the safety classifier while printing excerpts |

The trial is not comparable to B. It revised an existing draft and did not write one.

## What the host saw (`host_input_schema_excerpt.json`)

`experiments[].discriminates` and `hypotheses[].supporting_evidence_ids` were bare string arrays
with no description, both on the host and in the local build at `621bf3d`. Nothing in the schema
said that `discriminates` takes hypothesis ids, or that `evidence_links` is not read in place of
`supporting_evidence_ids`.

## Cause, replayed on the product path (`replay_measurements.json`)

`condition_B_payload_1.json`, replayed unchanged through `build_server()`, reproduces the host's
reply: the same 83 findings, and 337 KB of structured result. The MCP SDK also sends a ~505 KB
indented text copy of it.

- **Type error:** none. `["H1 vs H2", …]` is a list of strings, so it passes the type check.
- **Reference error:** 39 values in `discriminates` across E1–E6 are pair strings, not
  hypothesis ids → 39 `unknown_hypothesis_id`.
- **Derived from the reference error:** 39 `discrimination_claimed_without_predictions`, one per
  pair string. It cannot hold on its own: no prediction can name a value that is not an id. It was
  also listed twice, once in `findings` and once in `plan_analysis.findings`.
- **Input inconsistency, not a missing source:** 5 `unsupported_evidence_link` (H2–H6). Each had
  `supports` links to read spans in `evidence_links`, but an empty `supporting_evidence_ids`.
- **Independent of the reference error:** 3 predictions with basis `assumption` and no stated
  assumption (`E2:H1:aSMA_in_naive_recipient`, `E3:H1:clonal_bimodality`,
  `E4:H1:GATA6_protein`). They appeared only inside `plan_analysis.prediction_traces[].gaps`, not
  in `findings`.
- **Size:** `prediction_traces` was 229 KB of the 337 KB. 126 KB of that was each experiment's
  decision branches, copied onto every one of its 144 traces. `plan_analysis.experiments` was
  56 KB, 40 KB of it per-readout separated-pair detail.

## What changed

- **Schema** (in the contracts, published from there): `discriminates` says it takes
  `hypotheses[].id`, one per entry, not `"H1 vs H4"`, with example `["H1", "H4"]`.
  `supporting_evidence_ids` says `evidence_links` is not read in its place. The server does
  not split pair strings or fill in evidence ids.
- **Findings carry `field`, `value`, `case` and `caused_by`** where they apply. Only the derived
  finding gets `caused_by`. A real hypothesis that an experiment says it separates, but that has no
  prediction there, stays an independent finding.
- **`unsupported_evidence_link` has three cases:**
  - `supports_link_not_in_supporting_ids`: an input mismatch;
  - `only_non_supporting_links`: method, contradicts or scope_limit links only, so a real gap;
  - `no_grounded_support`: a real gap.
  None promotes an id into support.
- **`finding_groups`** (both views) groups by code, field, case and cause. Input problems come
  first, every location and value is kept, and derived findings are nested and counted.
  Prediction-trace gaps are included as their own groups.
- **`not_computed`** says what could not be computed and why. Not computed is not passed.
- **`view: "compact"`** (opt-in; the default `full` keeps every existing field):
  - `findings` and `plan_analysis` are `null`, not empty;
  - `plan_summary` carries pairs, unseparated pairs, mechanism-link gaps, evidence by study,
    limits and the full what-if `impact`;
  - `omitted` lists what was left out and how to get it.

## Replay results

| Payload | Findings | Before (host reply) | After, full | After, compact |
|---|---|---|---|---|
| `condition_B_payload_1.json` (first) | 83 | 333 KB | 359 KB | **27 KB**, 3 groups |
| `condition_B_payload_2.json` (revised) | 1 | 309 KB | 313 KB | **19 KB**, 1 group |
| `trial/draft_v2.json` | 0 | — | 314 KB | **21 KB**, 1 review group |

The first payload's compact reply has 3 groups:
- `unknown_hypothesis_id` ×39 (input), with `discrimination_claimed_without_predictions` ×39 nested;
- `unsupported_evidence_link` ×5 (input, `supports_link_not_in_supporting_ids`);
- `assumption_without_stated_assumptions` ×3 (review).

The full view grows slightly because the groups are added. The plan analysis is identical
across views and before/after, apart from the new keys on its findings: pairs, unseparated pairs,
pairs never separated, limits, evidence origins, and the what-if impact (H4, H1; E1, E5; ML2,
ML3). Fixing the input and changing the display are separate effects: the byte reduction comes
from the compact view alone, and the drop from 83 to 0–1 findings comes from fixing the input.

## Usability trial (`trial/`)

This was a fresh subagent context, given only the published tool schema, the first draft, and its
compact reply (`check_v1_compact.json`). It was not allowed to read repository source and could not
call the checker.

- **One revision** (`revise_v2.py`, `notes_v2.md`) fixed both input groups. As stored, the script reads `records/condition_B_payload_1.json` (byte-identical to the `draft_v1.json` it ran on) and was reformatted by `ruff format`. Re-running it reproduces `draft_v2.json` byte for byte.
- It filled `supporting_evidence_ids` only from existing `supports` links, and split the pair
  strings itself.
- It added one assumption by copying the draft's own sibling text verbatim. It left the other two
  unresolved rather than invent an assumption.
- **Second check** (`check_v2_compact.json`): 0 findings. The 2 assumption gaps are still visible
  as a review group.
- **Two check calls in total.** Outside the edited field families, v1 and v2 are identical.
- The trial agent reports that it needed nothing beyond the schema and the reply. It also reports
  that it used ~7 KB of the 38 KB reply (`finding_groups`, `not_computed`).

**This ran on the local product path (`build_server()` on this branch), not on the deployed
host.** The host still runs a build without `view` or the new descriptions, so no host
verification of this change has been done.

## Findings recorded, not fixed here

- **Collection order vs interpretation order.** B wrote "E1 first (hard order)" for E3–E5, which
  partly conflates the two. VCRP did not flag it. A kept them apart.
- **Breadth of explanations.** A named readout lag, population composition and baseline drift as
  separate explanations. B did not. Hypothesis breadth is not something the check computes.
- **KG scope.** All 12 mechanism links were `not_in_graph`, which is expected for an unregistered
  question and told the host nothing.
- The full view is still large: the decision-branch copy in each trace is kept for
  compatibility.

## Real-host compact trial (`host_trial/`, 2026-10-03)

**Host.** The connected `virtualcell` server was the local stdio process Claude Code starts from
`.mcp.json`. Its editable install ran this repository's `src/` at `d6d2b05`, and the process
started after that commit, so no restart was made.

**Trial.** A fresh subagent context was given the published tool and the stored first draft
(`records/condition_B_payload_1.json`, sha256 `d44100e2…`). It called the real host tool twice,
both times with `view: "compact"`:

- **Call 1:** `finding_count` 83, with three groups:
  - `unknown_hypothesis_id` ×39 (input), with `discrimination_claimed_without_predictions` ×39
    nested under it;
  - `unsupported_evidence_link` ×5 (input);
  - `assumption_without_stated_assumptions` ×3 (review).
- **One revision** (`revise.py` → `draft_v2.json`, sha256 `c336741b…`):
  - it split the pair strings into ids itself;
  - it copied `supports` links into `supporting_evidence_ids`;
  - it changed nothing else.
- **Call 2:** `finding_count` 0. The 3 assumption items remain as a review group, and the trial
  added no assumption text.
- **Unchanged across both calls:**
  - all evidence was `host_supplied`;
  - `scientific_validity_checked` was false;
  - what-if impact was H4, H1 / E1, E5.

**Before the two server calls**, the client rejected one attempt: "could not be parsed as JSON".
The draft had been wrapped in a single field the schema does not declare, and this rejection never
reached the server.

**Cost.** The agent read the compact replies directly, with no parsing script. The harness reported
353,823 tokens, 26 tool calls and 1,617 s for the trial context. That total is not split into
input, output and cache, and is not billing. Most of it was the model writing the ~130 KB draft out
as tool arguments, three times.

**Files.**
- `SHA256SUMS.as_run` holds the files as the session left them. That includes two intermediate
  slices of the draft the agent wrote (`evidence.min.json`, `experiments.min.json`), which are not
  committed.
- `SHA256SUMS` holds the committed copies. Only `revise.py` differs: its absolute paths were made
  relative, and `zip(..., strict=True)` was added for lint. It reproduces `draft_v2.json` byte for
  byte.

## Checking a draft by file (`file_input_trial/`)

**No existing path.** This host exposes no programmatic MCP call (no REPL tool), so nothing
existing could pass a file to the tool.

**`check_research_draft_file(path, sha256, view="compact")` was added.** It is registered only when
the stdio server starts with `VIRTUALCELL_MCP_DRAFT_DIR` set; the HTTP transport never passes a
directory. Behaviour:
- it reads a regular `.json` file of at most 2 MB, resolved with links followed, inside that
  directory;
- it hashes the bytes it read, refuses a mismatch, and parses those same bytes;
- it calls the inline `check_research_draft` through the server, so argument validation, findings,
  plan analysis and evidence classification are the inline tool's;
- it returns that result plus `input_file` (path, sha256, bytes);
- it never writes the file;
- reading the file does not make its evidence server-retrieved.

**Trial over a real MCP stdio session.** The client was a script, not the Claude Code host, against
a fresh `python -m virtualcell.mcp` with the variable set (`run_stdio_trial.py`, `run.json`). It
checked v1 and the host's own v2 by reference, both with `view: "compact"`:

| | arguments sent | bytes the server read from file | structured reply | text block | time |
|---|---|---|---|---|---|
| v1 | 117 B | 130,050 B | 27,147 B | 46,907 chars | 0.25 s |
| v2 | 117 B | 130,365 B | 21,001 B | 38,073 chars | 0.03 s |

Compared with the real-host replies for the same drafts, these fields are identical on both calls:
- `finding_count`, `finding_groups`, `not_computed`, `plan_summary` (including what-if impact),
  `omitted`;
- `evidence_origins` (all `host_supplied`), `not_checked` and `scientific_validity_checked`.

The only addition is `input_file`.

**Not done:** a Claude Code host using the file tool. The running host server was started without
the variable, and a session cannot gain it without an environment change and an MCP reconnect.
