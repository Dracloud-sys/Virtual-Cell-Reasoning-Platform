---
name: Claude-ready task
about: One fully-scoped unit of work for the Claude implementation routine
title: "[claude-ready] "
labels: claude-ready
---

<!--
This template is the contract the Claude routine executes against. It refuses to start
when the queue holds zero such issues (NO_READY_WORK) or more than one (AMBIGUOUS_QUEUE),
so keep exactly one open at a time.

Every section below is load-bearing. An empty "Forbidden paths" reads as "nothing is
forbidden", not as "the author had nothing to add" — write "none" explicitly instead.
-->

## Work ID

<!-- Short kebab-case slug. The routine branches as claude/<work-id>-<short-name>. -->

`pr21-`

## Roadmap anchor

<!-- Which roadmap item this is, quoted or linked, so the branch is traceable to a decision
     rather than to a conversation. See docs/roadmap.md, "What comes next, in order". -->

## Goal

<!-- One sentence. If it needs two, it is probably two issues. -->

## Shape of the work

- [ ] **Implementation** — the change is known and the work is to build it
- [ ] **Investigation-first** — the outcome may be an ADR explaining why the current
      structure stays; that counts as done, not as a failure to deliver

## Benchmark-first

<!-- Required by CLAUDE.md and not optional: the questions the platform must answer are
     written BEFORE the implementation. List them here, or name the scorecard/benchmark
     file the routine must add them to. Questions written afterwards only describe
     whatever got built. -->

## Allowed paths

<!-- Explicit list. The routine touches nothing outside it. -->

```
src/
tests/
docs/
CHANGELOG.md
```

## Forbidden paths

<!-- Write "none" if there genuinely are none. -->

```
src/virtualcell/reasoning/kernel/
```

## Kernel authorization

- [ ] **Not authorized** (default) — `src/virtualcell/reasoning/kernel/` takes zero changes
- [ ] **Authorized** — this milestone explicitly permits kernel changes, scoped below

<!-- If authorized, say exactly which files and why the change cannot live in a caller.
     A kernel bent to fit its third caller on first contact has not been validated. -->

## Non-goals

<!-- What this issue deliberately does not do, so the diff does not grow to meet an
     adjacent temptation. Findings over fixes: an abstraction gap discovered here gets
     recorded and pinned by a test, not fixed inside this milestone. -->

## Stop conditions

The routine reports **BLOCKED** and pushes nothing further when:

- resolving a failure requires expanding scope beyond Allowed paths
- the fix requires a scientific or domain judgment (that call is GPT's, not Claude's)
- <!-- issue-specific stop conditions -->

## Biological content policy

Existing claim text, `EvidenceTier`, citations and confidences do **not** change to make a
test pass. If this issue intends a deliberate change to any of them, state it here with the
literature grounding; otherwise leave as-is.

- [ ] No biological content changes intended
- [ ] Changes intended (specified below, with citations)

## Acceptance criteria

<!-- Machine-readable where possible. A green benchmark is agreement; prose is not. -->

- [ ]
- [ ]

## Verification expectations

`python scripts/verify.py` must pass in full. Expected scorecard results, which the routine
reports individually:

| Scorecard | Expected |
|---|---|
| immortalization | 10/10, **identical per-question scores** |
| adipogenesis | 10/10 |
| validation loop | 6/6 |
| genome editing | 10/10 |

A changed per-question score needs an explanation in the PR, not a shrug. Kernel diff
against `origin/main` must be empty unless authorized above.

## API / CLI / MCP parity

<!-- Does this change the query surface? If a capability lands in one entry point it lands
     in all three, or the issue says explicitly why not. -->

## Open domain questions

<!-- Anything Claude must not decide alone. Left unanswered, these become the PR's
     "unresolved questions" section. -->
