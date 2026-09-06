---
name: Claude-ready task
about: One fully-scoped unit of work for the automated implementation run
title: "[work-id] "
---

<!--
This template is the contract a run executes against, and `scripts/automation` checks it
section by section before anything is branched. A section that is missing, left as this
instructional comment, or filled with a bare `none`, stops the run with INVALID_SPEC.

The `claude-ready` label is NOT applied by this template. Filing an issue does not queue it.
A person adds the label once the contract below is complete and they approve it running
unattended — that label is the approval, so it must be an act, not a side effect.

Keep exactly one labelled issue open: zero reports NO_READY_WORK, two or more reports
AMBIGUOUS_QUEUE, and neither changes anything.
-->

## Work ID

<!-- Short kebab-case slug, e.g. `vcrp-ops-002`. The run branches as claude/<work-id>-<name>. -->

## Goal

<!-- One sentence. If it needs two, it is probably two issues. -->

## Work type

- [ ] **Implementation** — the change is known and the work is to build it
- [ ] **Investigation-first** — an ADR explaining why the current structure stays is a
      complete outcome, not a failure to deliver

## Pre-implementation verification questions

<!--
Required, and written BEFORE the implementation exists. List the questions the change must
answer, or name the scorecard/benchmark file the run must add them to. Questions written
afterwards only describe whatever got built.
-->

## Allowed paths

<!-- Explicit. Nothing outside this list is touched; a change that needs more stops the run
     with BLOCKED_SCOPE rather than widening the diff. -->

```
```

## Forbidden paths

<!-- Write `none - <reason>` if there genuinely are none. Blank does not read as "nothing to
     add", it reads as "nothing is forbidden". -->

```
src/virtualcell/reasoning/kernel/
```

## Kernel authorization

- [ ] **Not authorized** — `src/virtualcell/reasoning/kernel/` takes zero changes
- [ ] **Authorized** — this milestone permits kernel changes, scoped below

<!-- If authorized, name the files and why the change cannot live in a caller. A kernel bent
     to fit its third caller on first contact has not been validated, it has been widened. -->

## Non-goals

<!-- What this deliberately does not do. Findings over fixes: an abstraction gap discovered
     here gets recorded and pinned by a test, not fixed inside this milestone. -->

## Stop conditions

<!-- What makes the run report BLOCKED instead of continuing. Scope expansion and any
     scientific or domain judgement are always stop conditions; add the issue-specific ones. -->

## Acceptance criteria

<!-- Machine-readable where possible. A green benchmark is agreement; prose is not. -->

## Biological content change intent

- [ ] **No biological content changes intended**
- [ ] **Changes intended** — specified below, with citations

<!-- Existing claim text, EvidenceTier, citations and confidences never change to make a test
     pass. A deliberate change is stated here with its literature grounding. -->

## Interface impact

<!-- API / CLI / MCP. A capability that lands in one entry point lands in all three, or this
     says why not. Write `none - <reason>` when the change is not reachable from any of them. -->

## Verification expectations

`python scripts/verify.py` must pass in full, and the run reports each scorecard individually:

| Scorecard | Expected |
|---|---|
| immortalization | 10/10, **identical per-question scores** |
| adipogenesis | 10/10 |
| validation loop | 6/6 |
| genome editing | 10/10 |

A changed per-question score needs an explanation in the pull request, not a shrug. The
product-code and kernel diffs against the base ref must be empty unless authorized above.

## Open domain questions

<!-- Anything the run must not decide alone. Left unanswered, these become the pull request's
     "unresolved questions" section. -->
