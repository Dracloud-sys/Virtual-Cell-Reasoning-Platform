# Unattended run: runbook

How the scheduled implementation run starts, what each refusal means, and what to do when one
of them fires. The gate itself is `scripts/automation`; its questions are pinned in
`tests/automation`. This file is the part that cannot be a test: the procedures a person
follows afterwards.

## The one-item queue

A run works from **exactly one open issue carrying the `claude-ready` label**.

| Open labelled issues | Outcome |
|---:|---|
| 0 | `NO_READY_WORK` — nothing changed |
| 1 | the run proceeds |
| >1 | `AMBIGUOUS_QUEUE` — nothing changed |

Refusing to choose between two is deliberate. Picking which work matters next is strategy, and
an implementer that picks for itself has quietly taken that decision.

**Filing an issue does not queue it.** The template no longer applies the label, because a
template that labels on creation makes queueing a side effect of opening a tab. A person adds
`claude-ready` once the contract is complete and they approve it running unattended. The label
*is* the approval.

## What each refusal means

| Status | What happened | What to do |
|---|---|---|
| `NO_READY_WORK` | queue read fine, nothing approved | nothing. This is the normal quiet night |
| `AMBIGUOUS_QUEUE` | two or more labelled issues | remove the label from all but one |
| `INVALID_SPEC` | a section is missing, unfilled, or self-contradictory | fix the issue body; the report names every bad section |
| `BLOCKED_GITHUB_ACCESS` | the query itself failed | check repository access on the routine before anything else — **this is never read as an empty queue** |
| `BLOCKED_ENVIRONMENT` | interpreter below 3.12, or dependencies missing | fix the environment's setup script; do not hand-install and re-run, or the next run breaks the same way |
| `ALREADY_RUNNING` | another run holds the lock | wait, or follow *Recovery* below if nothing is actually running |
| `AWAITING_REVIEW` | a pull request for this work is open | review it. A second branch for the same issue is a fork, not progress |
| `BLOCKED_SCOPE` | a needed change is outside the issue's allowed paths | widen the issue deliberately, or split the work. Never widen the diff |

## Re-running

A run is safe to repeat. It reads the queue again, re-validates the spec, and stops in the
same place unless the cause is gone.

1. Fix the cause the status names.
2. Trigger the routine (**Run now**), or wait for the schedule.
3. Confirm the outcome in the run record comment, not in the run's green status — a green run
   status means the container exited cleanly, which is also what a completely blocked run does.

To re-run against a **revised** pull request rather than a new branch, the instruction has to
name the pull request and the head SHA it was written against, and be approved by a person.
An instruction whose head SHA no longer matches has expired: the branch moved, so the same
sentence is now a request about code its author has not read. Already-applied instructions are
recorded by identifier and are not applied twice.

## Recovery after a crash

A run that dies between taking the lock and finishing leaves the lock held, and every later run
reports `ALREADY_RUNNING`.

1. Confirm nothing is running: check the routine's run list for an in-flight session.
2. Delete the lock entry for that work id (`FileLockStore` writes `<work-id>.lock`; a container
   that has been reclaimed takes its lock with it, so this only matters within one container).
3. Check for a half-pushed branch: `git ls-remote --heads origin 'claude/*'`. A branch with no
   pull request is a crashed run's leftovers; delete it or open the pull request deliberately.
4. Re-run.

The gate releases the lock itself on every refusal that happens after it was taken, so a
blocked run does not need this. Only a killed process does.

## Known gap: the lock is per-container

`FileLockStore` is atomic — `O_CREAT | O_EXCL` is one syscall and the loser gets a refusal —
but it is atomic *within one filesystem*. Scheduled runs each get their own container and
therefore their own empty lock directory, so two overlapping scheduled runs cannot see each
other's lock.

Closing this needs a store both runs can reach, whose creation fails for the loser. Creating a
remote git ref has that shape (the second creation is rejected), and `LockStore` is a protocol
precisely so that implementation can be dropped in without touching the gate.

**Until it is closed, the schedule stays off.** Concurrency is currently prevented by the
routine being disabled and runs being started by hand, which is a real control but an
operational one, not a technical one. This is recorded here rather than fixed inside this work
item, per the findings-over-fixes rule in `CLAUDE.md`.

## Routine settings

Changed only as far as this work item needed. **Model and cadence are unchanged.**

| Setting | Before | After |
|---|---|---|
| Schedule | `0 16 * * *` UTC (01:00 KST) | unchanged |
| Model | `claude-opus-5` | unchanged |
| Enabled | `false` | `false` — re-enabling needs explicit approval |
| Repositories | none attached | `Dracloud-sys/Virtual-Cell-Reasoning-Platform` |
| Prompt | reported only into its own session | also posts a run record comment |

The repository attachment was the defect behind three empty runs: with no source attached the
container cloned nothing, so the run could not read `CLAUDE.md`, could not query the queue, and
could not have opened a pull request. It was diagnosed by the absence of a run record, which is
why the record exists.

**Re-enabling the schedule is not part of this work item.** A run driven by hand proves the
gate; it does not prove the scheduled path end to end. That verification comes after merge,
against a real scheduled run, and needs the per-container lock gap above closed first.
