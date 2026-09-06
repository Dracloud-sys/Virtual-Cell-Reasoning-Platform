# Unattended run: runbook

How the scheduled implementation run starts, what each refusal means, and what to do when one
of them fires. The gate is `scripts/automation`; its questions are pinned in `tests/automation`.
This file is the part that cannot be a test: the commands, and the procedures a person follows
afterwards.

## The commands the Routine runs

The gate is not advice the agent may take. It is a sequence of processes, and each exit code
decides whether the next step happens. **Run them from the repository root** — that is where a
scheduled run starts, and the command has to work there with nothing set up:

```bash
# phase 1 - read the queue, validate the contract, take the lock
python scripts/automation/cli.py preflight --request phase1.json --token .automation/lock.json

# ...the agent now queries GitHub AGAIN, after the lock exists...

# phase 2 - submit that re-read and receive permission
python scripts/automation/cli.py confirm --request phase2.json --token .automation/lock.json \
    --proceed-marker .automation/proceed.json

# ...the implementation happens here...

# after the work, before any push - judge the real diff and run the full gate
python scripts/automation/cli.py postflight --request phase1.json --token .automation/lock.json \
    --base origin/main --unchanged src/virtualcell/ --revision "$APPROVED_REVISION_ID"

# give the lock back
python scripts/automation/cli.py release --request phase1.json --token .automation/lock.json
```

**Four commands, not one, because the run has four moments where it can be wrong and one
process cannot straddle them.**

`preflight` takes the lock and *stops*. Taking the lock is not permission to work: it writes a
lock token and exits. `confirm` is the only command that writes the proceed marker, and it does
so only when the token matches, the evidence was captured **after** the lock was taken, and the
issue and its pull requests still look the way phase one decided about. That separation is the
whole point — an earlier version parsed both "before" and "after" snapshots out of one file
written before the lock existed, which is not a re-read of anything.

`postflight` runs after the implementation and before the push. It is where `BLOCKED_SCOPE`
actually happens: real changed paths from `git diff --name-status -M base...HEAD`, judged
against the issue's own allowed and forbidden paths, with renames checked at both ends and the
kernel guarded unless the issue authorises it. Then `scripts/verify.py` in full, and only then
is the applied revision id recorded. Nothing is pushed unless this exits 0.

`release` uses the token from disk, so the process that gives the lock back does not have to be
the one that took it.

**Exit 0 means the step succeeded and the next may begin, and nothing else does:**

| Code | Status | Code | Status |
|---:|---|---:|---|
| 0 | `READY_TO_IMPLEMENT` | 15 | `BLOCKED_SCOPE` |
| 10 | `NO_READY_WORK` | 16 | `ALREADY_RUNNING` |
| 11 | `AMBIGUOUS_QUEUE` | 17 | `AWAITING_REVIEW` |
| 12 | `INVALID_SPEC` | 18 | `WORK_ID_MISMATCH` |
| 13 | `BLOCKED_GITHUB_ACCESS` | 19 | `AMBIGUOUS_PULL_REQUEST` |
| 14 | `BLOCKED_ENVIRONMENT` | | |

### Building the requests

The agent calls its GitHub tools and writes the **raw responses** into the request file. It does
not summarise them: parsing, filtering and refusing all happen in code that a test can drive.

```json
{
  "work_id": "vcrp-ops-002",
  "captured_at": "2026-09-06T05:45:00+00:00",
  "queue_pages": [ "<raw list_issues response>", "...every page..." ],
  "queue_error": null,
  "pull_requests": [ "<raw list_pull_requests response>" ],
  "approvals": [ "<raw review / review-comment payloads>" ],
  "existing_branches": ["claude/vcrp-ops-002-thing"],
  "lock":  {"kind": "git-ref", "remote": "origin", "workdir": "."},
  "state": {"kind": "git-ref", "remote": "origin", "workdir": "."}
}
```

Five fields carry more weight than they look:

- **`queue_error`** is for the case where the query *failed*. Never pass an empty page list to
  represent a failure — that is the confusion the whole package exists to prevent. A REST error
  envelope (`{"message": "Bad credentials", "status": "401"}`) is also refused, because it
  carries no `issues` collection at all.
- **every page** goes in `queue_pages`. If the last page says `hasNextPage`, the read is
  refused: one issue plus "there is more" would dispatch work while a second approved issue sat
  unseen on page two.
- **`captured_at`** is required on the phase-two request, and must postdate the lock. Without it
  the confirmation cannot be shown to be a re-read.
- **`approvals`** are the raw review payloads. The parser derives the record id, the author
  login, the body, the pull request and the full commit id from GitHub's own fields — an
  `approved_by` the agent writes alongside them is ignored.
- **`approvers`** are *not* taken from the request. They come from
  [`run_approvers.json`](run_approvers.json), which is committed, so changing who may approve a
  revision is a reviewable commit rather than a line the agent can write for itself. An empty
  list is a configuration error, never "no restriction".

## The one-item queue

A run works from **exactly one open issue carrying the `claude-ready` label**.

| Open labelled issues | Outcome |
|---:|---|
| 0 | `NO_READY_WORK` — nothing changed |
| 1 | the run proceeds |
| >1 | `AMBIGUOUS_QUEUE` — nothing changed |

Refusing to choose between two is deliberate. Picking which work matters next is strategy, and
an implementer that picks for itself has quietly taken that decision.

**Filing an issue does not queue it.** The template does not apply the label, because a template
that labels on creation makes queueing a side effect of opening a tab. A person adds
`claude-ready` once the contract is complete and they approve it running unattended. The label
*is* the approval.

## What each refusal means

| Status | What happened | What to do |
|---|---|---|
| `NO_READY_WORK` | queue read fine, nothing approved | nothing. This is the normal quiet night |
| `AMBIGUOUS_QUEUE` | two or more labelled issues | remove the label from all but one |
| `INVALID_SPEC` | a section is missing, unfilled, placeholder-filled, or self-contradictory | fix the issue body; the report names every bad section |
| `WORK_ID_MISMATCH` | the issue declares a different work id | fix whichever is wrong. The **issue** is authoritative |
| `BLOCKED_GITHUB_ACCESS` | the query failed, or the lock store was unreachable | check repository access on the Routine first — this is never read as an empty queue |
| `BLOCKED_ENVIRONMENT` | interpreter below 3.12, or dependencies missing | fix the environment's setup script; do not hand-install and re-run, or the next run breaks the same way |
| `ALREADY_RUNNING` | another run holds the lock | wait, or follow *Recovery* below if nothing is actually running |
| `AWAITING_REVIEW` | a pull request for this work is open | review it. A second branch for the same issue is a fork, not progress |
| `AMBIGUOUS_PULL_REQUEST` | two open pull requests claim this work id | close or retarget one. The run will not pick |
| `BLOCKED_SCOPE` | a needed change is outside the issue's allowed paths | widen the issue deliberately, or split the work. Never widen the diff |

## Revising a pull request that is under review

The default is that a run may not touch it. The exception needs all four of:

1. an **approval record id** — the GitHub review or comment the instruction came from;
2. an **approver on the committed list** in `run_approvers.json`; a name the agent writes into
   its own request is a string, not an approval, and an empty list approves nobody;
3. the **full 40-character head SHA** the instruction was written against. Once the branch
   moves the instruction has expired: the same sentence is now a request about code its author
   has not read. Abbreviations are refused rather than prefix-matched;
4. **not already applied.** Applied ids live in a git ref (`refs/vcrp-state/applied-revisions`),
   so a restarted run reads what its predecessor did instead of doing it again. That store is
   fail-closed: a ref that does not exist yet is an empty set, but a ref that could not be
   *reached* blocks the run. Reading "nothing has been applied" out of a failed fetch is exactly
   how an approved revision gets carried out twice.

Anything that fails these is reported in the `AWAITING_REVIEW` detail — passed over, never
silently ignored.

## Re-running

A run is safe to repeat. It reads the queue again, re-validates the spec, and stops in the same
place unless the cause is gone.

1. Fix the cause the status names.
2. Trigger the Routine (**Run now**), or wait for the schedule.
3. Confirm the outcome in the run record comment and the exit code — **not** in the run's green
   status. A green run status means the container exited cleanly, which is also what a
   completely blocked run does.

## Recovery after a crash

A run that dies between taking the lock and finishing leaves the lock held, and every later run
reports `ALREADY_RUNNING`.

1. Confirm nothing is running: check the Routine's run list for an in-flight session.
2. Inspect the lock: `git ls-remote origin 'refs/vcrp-locks/*'`. The commit message names the
   owner and when it was taken.
3. Prefer the token: if `.automation/lock.json` survived, `release` drops the lock with a
   compare-and-swap and no override is needed. The token is on disk precisely so the process
   that gives the lock back need not be the one that took it.
4. Only if the token is gone, delete the ref by hand:
   `git push origin :refs/vcrp-locks/<work-id>`. This is the one manual override, and it is
   manual on purpose — `release()` refuses to drop a lock the caller cannot prove it holds,
   because a crashed run is exactly when another run would love to clear it and start.
5. Check for a half-pushed branch: `git ls-remote --heads origin 'claude/*'`. A branch with no
   pull request is a crashed run's leftovers. The next run reports it as `resume_branch` and
   continues on it rather than opening a second one; delete it only if you want a fresh start.
6. Re-run.

The gate releases the lock itself on every refusal that happens after it was taken, so a blocked
run does not need this. Only a killed process does.

## Concurrency

`GitRefLockStore` pushes an **orphan commit** to `refs/vcrp-locks/<work-id>`. A push that would
not fast-forward the existing ref is rejected by the server, and an orphan can never be an
ancestor of anything, so while the ref exists every other run's push is rejected. Exactly one
creation wins, and the remote decides — not either contender's belief about the other.

That argument has a hole, and it was live: it assumes the two contenders build *different*
commits. Git objects are content-addressed, so two runs with the same work id, the same owner
and the same one-second timestamp built the **same commit**, the second push found the ref
already pointing at that object, git said "Everything up-to-date" and exited 0, and both runs
concluded they held the lock — `[True, True]`. Every lock commit now carries a 32-hex nonce from
`secrets`, an up-to-date push counts as contention, and each run gets a unique owner. The
uniqueness is the mutual exclusion; the compare-and-swap only enforces it.

Three distinctions the store refuses to blur:

- **rejected is not failed.** A rejected push means somebody else holds the lock. A push that
  failed for any other reason raises `LockUnavailable`, which the gate reports as
  `BLOCKED_GITHUB_ACCESS`. Treating an unreachable remote as a free lock would be the worst
  available reading.
- **holding is not owning.** `release` drops only a lock this run took, with
  `--force-with-lease` so the delete is itself a compare-and-swap.
- **state is not session memory.** Applied revision ids are in a ref, not in a variable.

`tests/automation/test_gitref_lock.py` races six threads through one barrier against one bare
repository and asserts that exactly one comes back holding it. The earlier version of this test
called the store twice in sequence, which demonstrated bookkeeping and nothing about a race.

`FileLockStore` remains for a single container (two processes, one filesystem). It cannot see a
run in another container and must not be used for the scheduled path.

## Routine settings

Changed only as far as this work item needed. **Model and cadence are unchanged.**

| Setting | Before | After |
|---|---|---|
| Schedule | `0 16 * * *` UTC (01:00 KST) | unchanged |
| Model | `claude-opus-5` | unchanged |
| Enabled | `false` | `false` — re-enabling needs explicit approval |
| Repositories | none attached | `Dracloud-sys/Virtual-Cell-Reasoning-Platform` |
| Prompt | reported only into its own session | posts a run record comment; calls `python -m automation preflight` and obeys its exit code |

The repository attachment was the defect behind three empty runs: with no source attached the
container cloned nothing, so the run could not read `CLAUDE.md`, could not query the queue, and
could not have opened a pull request. It was diagnosed by the absence of a run record, which is
why the record exists.

**Re-enabling the schedule is not part of this work item.** A run driven by hand proves the
gate; it does not prove the scheduled path end to end. That verification comes after merge,
against a real scheduled run.
