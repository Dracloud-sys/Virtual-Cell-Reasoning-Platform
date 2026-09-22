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

| case | what it probes |
|---|---|
| `ecm_scaffold_single_cell.json` | the ECM question as originally asked: a rate-matching problem, one cell type, no animal arm |
| `contradicting_and_context_mismatch.json` | two of the caller's own runs disagree **and** differ in donor, lot and operator at once; a `derived_inference` rests only on the run that agreed with it; a `model_prior` offers a rival mechanism nobody measured |
| `unrelated_subject.json` | a hepatocyte metabolism question — does the same path work off the subject it was demonstrated on? |

`species_mismatch.json` is **excluded** and the runner skips it by name. Its only span is a
placeholder DOI that says so in its own text, and scoring a design built on an invented
paper would measure how well a model reasons from a fabrication.

## Requirements

* Python 3.12 (the project floor).
* The project installed with the LLM extra:
  ```bash
  uv venv --python "$(command -v python3.12)" .venv
  uv pip install --python .venv/bin/python -e ".[dev,llm]"
  ```
  `[llm]` is what installs `anthropic`; without it the run stops with `BackendUnavailable`
  and exits without calling anything.
* `ANTHROPIC_API_KEY` exported in the shell. **Do not put a key in a file in this
  repository, and do not paste one into a chat.** The runner reads it from the environment
  through the SDK and never prints it.
* The model: whatever `get_settings().llm_model` resolves to, or `--model` to pin one
  explicitly. Both conditions always get the same value — that is not overridable
  separately, because separately is how a comparison becomes meaningless.

## Run it

**Dry run first. This is the default and it calls nothing:**

```bash
python tests/benchmarks/research/run/run_comparison.py
```

It writes every prompt it would send, plus a crude token estimate (characters ÷ 4, not a
quote — apply your own current per-token pricing). Six calls: three cases × two conditions.

**Then, only if you have approved that spend:**

```bash
python tests/benchmarks/research/run/run_comparison.py --spend-approved
```

Useful flags: `--model`, `--max-output-tokens` (applies to both conditions), `--case`
(repeatable), `--conditions b` or `c` (running one alone is not a comparison), `--out`.

## What you get

Under `out/`, per case:

| file | what it is |
|---|---|
| `request.json` | the request as the contract validated it, evidence snapshot and content hashes included |
| `prompt_b.txt` / `prompt_c.txt` | exactly what was sent, system and user parts labelled |
| `b_raw.txt` / `c_raw.txt` | the model's reply **before anything parsed it** |
| `c_report.json` | the checked report |
| `c_report.txt` | the same report as text — **rendered from the same call**, not a second one |
| `b_call.json` / `c_call.json` | model requested and served, tokens, stop reason, measured `elapsed_seconds`, and the limits the call ran under |
| `../manifest.json` | every attempted run and how it ended, successes and failures alike |
| `../run_config.json` | commit, model, prompt version, limits, which cases ran |

Two files are kept apart on purpose. `*_raw.txt` is what the model said; `c_report.json` is
what survived checking. Reading only the second hides everything the check caught, which is
the more interesting half.

`elapsed_seconds` is **measured**. The `timeout_seconds_per_request` and
`max_request_attempts` recorded next to it are settings; they do not multiply into a
deadline and none is enforced.

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
