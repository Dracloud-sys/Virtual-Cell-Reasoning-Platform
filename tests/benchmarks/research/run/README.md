# Running the B/C comparison on a machine that has a key

> **Status: not performed.** No design in this repository has ever been produced by a model.
> The environment this was built in has no `ANTHROPIC_API_KEY`, no `ANTHROPIC_AUTH_TOKEN`
> and no `anthropic` package. The Claude-prefixed variables present in it belong to the
> Claude Code harness's own session, and a Claude subscription is not an API credential for
> this Python backend — treating one as the other would be spending on an authorisation
> nobody gave. Repeating that check a fourth time produces no new information, so what is
> here instead is everything needed to run it somewhere that *is* authorised.

Everything below is committed and inspectable **before** anything is spent: the requests,
the evidence as the contract sees it, the exact prompt both conditions would receive, the
command, and the review sheet that was written before any output existed.

## What it compares

| | condition |
|---|---|
| **B** | the same model, the same evidence, answering as a competent assistant would |
| **C** | the same model, the same evidence, through `ResearchService` |

Matched on purpose: same model, same `max_tokens`, same per-request timeout and retry
ceiling, one call each, and **the same user-side prompt**, produced by the same
`build_prompt` that `ResearchService` uses — so C cannot win on having been given a cleaner
transcription of the evidence. The only deliberate difference is the system prompt.

Each call is a fresh stateless request. B never sees C's answer and C never sees B's.

**B is not weakened.** Its instruction asks for the best answer a capable assistant would
give. If B wins, that is the result.

## The three cases

> **Every observation in these files is invented for development.** Nobody ran these
> experiments. The `user_observation` items are **inputs in the shape a caller's observation
> would take** — the label says what kind of thing the model is being handed, not that the
> measurement was performed. Donor numbers, passage numbers, replicate counts and kPa values
> are all constructed to make a particular reasoning failure visible. None of them is data,
> and none may be cited as a result of anything.

| case | what it probes |
|---|---|
| `ecm_scaffold_single_cell.json` | the ECM question as originally asked: a rate-matching problem, one cell type, no animal arm |
| `contradicting_and_context_mismatch.json` | two of the caller's own runs disagree **and** differ in donor, lot and operator at once; a `derived_inference` rests only on the run that agreed with it; a `model_prior` offers a rival mechanism nobody measured |
| `unrelated_subject.json` | a hepatocyte metabolism question — does the same path work off the subject it was demonstrated on? |

`contradicting_and_context_mismatch.json` contains **no `retrieved_source`**, so no invented
paper was put into its input — that is a statement about the file, and only about the file.
**It does not mean the model cannot fabricate a citation.** A model can name a paper in any
free-text field it writes, and nothing in this bundle verifies that such a name refers to
anything real. Whether it did so is one of the things a reader has to look for.

`species_mismatch.json` is **excluded** and the runner skips it by name. Its only span is a
placeholder DOI that says so in its own text, and scoring a design built on an invented
paper would measure how well a model reasons from a fabrication.

## What this comparison is, and is not

It compares **a system prompt, a required output structure, and a post-hoc check** against a
plain answer from the same model on the same material. That is all three of the things C
adds over B, and all three are the things under test.

It is **not** a test of automated literature search: P2 does not exist, no retrieval runs,
and the evidence is whatever the case file injected. It is **not** a test of knowledge-graph
reasoning: nothing here reads or writes the graph. It is **not** a measure of factual
accuracy against the literature, because no case is scored against real papers.

It is a **development** comparison on three cases that the implementing session wrote and can
see. It can show whether the difference is worth pursuing. It cannot conclude that it is.

## Requirements

* Python 3.12 (the project floor).
* The project installed with the LLM extra. `[llm]` is what installs `anthropic`; without it
  the run stops with `BackendUnavailable` and exits `3` without calling anything.

**Use the same interpreter to install and to run.** Installing into a virtual environment
and then running a bare `python` is the commonest way to end up with `anthropic` installed
somewhere the run cannot see it — and on Windows a `python` on `PATH` is usually *not* the
one in `.venv-live`. Spell the interpreter out both times.

**Windows (PowerShell or cmd):**

```
py -3.12 -m venv .venv-live
.\.venv-live\Scripts\python.exe -m pip install -U pip
.\.venv-live\Scripts\python.exe -m pip install -e ".[dev,llm]"
```

Set the key for the session — in the shell, never in a file in this repository, and never
pasted into a chat:

```
# PowerShell
$env:ANTHROPIC_API_KEY = "<your key>"
# cmd
set ANTHROPIC_API_KEY=<your key>
```

**macOS / Linux:**

```bash
uv venv --python "$(command -v python3.12)" .venv-live
uv pip install --python .venv-live/bin/python -e ".[dev,llm]"
export ANTHROPIC_API_KEY='<your key>'
```

The runner reads the key from the environment through the SDK and never prints it.

The model is whatever `get_settings().llm_model` resolves to, or `--model` to pin one
explicitly — **pin it for a real run**, so the output records which model answered rather
than which alias was configured that day. Both conditions always get the same value; that is
not separately overridable, because separately is how a comparison becomes meaningless.

## First run: one ECM case, condition C only

Start here rather than with all six calls. One call, one case, the condition that exercises
the product path.

**Step 1 — dry run. This is the default, it calls nothing and costs nothing:**

```
# Windows
.\.venv-live\Scripts\python.exe tests\benchmarks\research\run\run_comparison.py ^
  --case ecm_scaffold_single_cell.json --conditions c

# macOS / Linux
.venv-live/bin/python tests/benchmarks/research/run/run_comparison.py \
  --case ecm_scaffold_single_cell.json --conditions c
```

Read the `prompt_c.txt` it writes. That is exactly what would be sent.

**Step 2 — the real call, only if you have a credential and have approved this spend:**

```
# Windows
.\.venv-live\Scripts\python.exe tests\benchmarks\research\run\run_comparison.py ^
  --case ecm_scaffold_single_cell.json --conditions c ^
  --model <exact-model-id> --out runs\ecm-c-001 --spend-approved

# macOS / Linux
.venv-live/bin/python tests/benchmarks/research/run/run_comparison.py \
  --case ecm_scaffold_single_cell.json --conditions c \
  --model <exact-model-id> --out runs/ecm-c-001 --spend-approved
```

One call: roughly 790 input tokens and up to 4,096 output (the dry run prints the
figures; they are characters÷4, not a quote). `--out` must name a folder that does
not exist or is empty; omit it and a new timestamped folder under `out/` is used.

The full six-call comparison is the same command without `--case` and `--conditions`.

Other flags: `--max-output-tokens` (applies to both conditions, so they stay matched),
`--case` is repeatable.

## Exit codes

The same vocabulary `virtualcell research` uses, so a script reading one does not need a
second:

| | |
|---|---|
| `0` | ran clean, or a dry run did what it was asked |
| `1` | bad usage — an output folder that is not empty, a case that does not exist |
| `3` | no provider: **nothing ran** |
| `4` | a provider ran and a call failed |
| `5` | report(s) produced carrying integrity findings |

A failure outranks a finding: a finding is information about a report that exists, and a
failure means one does not.

## What you get

Per case, in the run's own folder:

| file | what it is |
|---|---|
| `request.json` | the request as the contract validated it, evidence snapshot and content hashes included |
| `prompt_b.txt` / `prompt_c.txt` | exactly what was sent, system and user parts labelled |
| `b_raw.txt` / `c_raw.txt` | the model's reply **before anything parsed it** |
| `b_call.json` / `c_call.json` | model requested and served, tokens, stop reason, measured `elapsed_seconds`, and the limits the call ran under |
| `c_report.json` | the checked report |
| `c_report.txt` | the same report as text — **rendered from the same call**, not a second one |
| `manifest.json` | every attempted run and how it ended, rewritten after each one |
| `run_config.json` | commit, model, prompt version, limits, which cases ran |

**`*_raw.txt` and `*_call.json` are written the instant the reply arrives** — before the JSON
is parsed and before the payload is checked. A reply that arrives and then fails checking was
still received and still billed for, and it used to leave nothing behind but an error
message. If no reply ever arrives, neither file is written: an invented raw text or a guessed
token count would be worse than the gap.

`*_raw.txt` is what the model said; `c_report.json` is what survived checking. Reading only
the second hides everything the check caught, which is the more interesting half.

`elapsed_seconds` is **measured**. The `timeout_seconds_per_request` and
`max_request_attempts` recorded next to it are settings; they do not multiply into a
deadline and none is enforced.

Each run gets its own folder and nothing is ever deleted to make room. A folder holding one
run's manifest and another run's reports is wrong in a way that looks fine.

## Reading the results

Use `review_sheet.md`, which was written before any of this ran and must not be edited once
outputs exist.

The one thing to hold on to while reading: **format compliance is not research quality.**
C returns JSON and B returns prose, so any structural check hands C a win it has not earned.
The integrity findings recorded for C are checkable defects — a citation to an id nobody
supplied — not a judgement of the biology, and B has no equivalent, so that column cannot be
compared across conditions.

Report every case and both answers, including where C looks worse.

## Reading the prompts without running anything

`prompts/` holds the committed output of a dry run: each case's `request.json` and the two
prompts as they would be sent. Regenerate with the dry-run command above.

A person can paste a prompt into a chat window and read what comes back. That is a useful
sanity check on the prompt, and **its result is not a result of this comparison**: it is not
the CLI, not `ResearchService`, not the same limits, not budget-matched, and nothing checked
its output. Anything obtained that way is reported as a manual prompt inspection, never as a
VCRP end-to-end run.
