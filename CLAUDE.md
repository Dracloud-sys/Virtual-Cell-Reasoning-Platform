# Working in this repository

Facts about this environment and this project's conventions that are expensive to rediscover.
Everything here was learned by getting it wrong at least once.

## Verification

**One command, always:**

```bash
python scripts/verify.py
```

It runs the full suite, the benchmark suite separately, **every** scorecard (discovered by
glob, not listed), `ruff check`, `ruff format --check`, and the kernel diff against
`origin/main`. `--fast` skips the scorecard tables; `--no-kernel-diff` skips the git
comparison when the base ref is not fetched.

Do not assemble this by hand. A gate composed from memory drifts, and a run that quietly
skipped a scorecard looks exactly like a run that passed.

**Never point pytest's `--basetemp` inside the repository.** Fixture files written there are
picked up by the next `ruff check .` as phantom lint errors and linger as untracked noise.
`verify.py` uses a system temp directory and cleans it up.

## Environment

- Python 3.12 lives at `C:\Users\dohf\AppData\Local\Programs\Python\Python312`. In Git Bash,
  prefix commands with `PATH="/c/Users/dohf/AppData/Local/Programs/Python/Python312:$PATH"`.
- Repository path contains non-ASCII characters. Prefer absolute paths and let tools resolve
  them; some Windows console encodings (cp949) cannot print em dashes, so avoid printing
  file contents with `print()` in throwaway scripts.
- Ruff order that converges: `ruff check --fix` → `ruff format` → `ruff check`. Running
  `format` before `--fix` can leave import blocks unsorted.

## Writing files

**Use the Write tool, not a bash heredoc, for anything containing quotes, apostrophes or
nested code.** Heredocs fail on this content in ways that look like an EOF parse error and
leave no file behind — and if the heredoc is in an `&&` chain, the failure is easy to
misattribute to the next command.

For patching an existing file, a small Python script (written with Write, then executed) is
more reliable than inline `sed`.

## Development method

**Benchmark-first, and it is not optional.** Write the questions the platform must answer
*before* the implementation. PR15 and PR18 both had benchmark questions that changed the
design; questions written afterwards only describe whatever got built.

A scorecard must run the **product path** (the domain pack / agent entry point that the API
and CLI use), never a private re-implementation. This is the PR10b rule: a benchmark scoring
a copy of the logic scores nothing.

**Findings over fixes.** If a milestone reveals an abstraction gap, record it — in the docs,
pinned by a test — rather than fixing it inside that milestone. A kernel bent to fit its
third caller on first contact has not been validated, it has been widened until the test
passed. Existing findings live in `docs/genome_editing_vertical.md` and
`docs/immortalization_validation_axes.md`.

## Invariants that must not break

| | |
|---|---|
| `src/virtualcell/reasoning/kernel/` | **zero changes** unless a milestone explicitly authorises one. Imports nothing from `virtualcell.agents` (AST test). |
| `src/virtualcell/core/consumption.py` | imports nothing from `virtualcell` at all (AST test). |
| `platform/service.py`, `domains.py`, `description.py`, `api/main.py`, `cli.py` | name no vertical (AST test). |
| each vertical under `agents/` | imports no other vertical (AST test). |
| scorecards | immortalization 10/10 with **identical per-question scores**, adipogenesis 10/10, validation loop 6/6, genome editing 10/10. A changed per-question score needs an explanation, not a shrug. |
| claim text, evidence tiers, citations, confidences | do not change these to make something else convenient. |

## Adding a domain

One line in `SHIPPED_DOMAINS` (`platform/bootstrap.py`) makes a domain routable, seeded,
describable and transparent. If adding one requires touching an interface, the boundary
leaked. A pack must implement `domain`, `supported_tasks`, `describe()`,
`validate_experiment()` and `execute()`; the registry refuses a pack missing the first four,
and `validate_pack()` checks every declared axis against the pack's own validation.

Declare axes **once**, as `AxisDescription`s. The description and the consumption ledger are
both derived from that declaration — do not restate the axis list anywhere.

## Git and PRs

- Commit trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Stage explicit paths (`git add CHANGELOG.md docs src tests`), not `git add -A`. `AGENTS.md`
  is untracked on purpose and must stay that way.
- **CI runs only on push-to-`main` and PRs targeting `main`** (`.github/workflows/`). A PR
  stacked on another branch gets **no checks**, and retargeting it later does not fire one
  either — `pull_request: edited` is not in the default event set. Either merge the parent
  **with** `--delete-branch` (auto-retargets *and* fires the event) or close/reopen the PR.
- Do not commit or push unless asked.

## Reading order for context

1. `docs/roadmap.md` — what shipped, in order, and what is next
2. `docs/architecture.md` — the layers and where a boundary sits
3. the vertical doc for whatever is being changed
