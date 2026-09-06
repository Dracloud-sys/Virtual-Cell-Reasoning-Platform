# Unattended run: runbook

How the scheduled implementation run starts, what each refusal means, and what to do when one
of them fires. The gate is `scripts/automation`; its questions are pinned in `tests/automation`.
This file is the part that cannot be a test: the commands, and the procedures a person follows
afterwards.

## The commands the Routine runs

The gate is not advice the agent may take. It is a sequence of processes, and each exit code
decides whether the next step happens. **Run them from the repository root** — that is where a
scheduled run starts:

```bash
# phase 1 - read the queue, validate the contract, take the lock. NOT permission to work.
python scripts/automation/cli.py preflight --request phase1.json --token .automation/lock.json

# ...the agent now queries GitHub AGAIN, after the lock exists...

# phase 2 - submit that re-read; this is what grants permission
python scripts/automation/cli.py confirm --request phase2.json --token .automation/lock.json \
    --confirmation .automation/confirmation.json --proceed-marker .automation/proceed.json

# ...the implementation happens here...

# before any push - judge the real diff and run the full gate
python scripts/automation/cli.py postflight --request phase2.json --token .automation/lock.json \
    --confirmation .automation/confirmation.json --unchanged src/virtualcell/

# ...the push happens here: git push origin HEAD:<the branch phase one bound>...

# after the push - ask the remote what the branch carries, then record and release
python scripts/automation/cli.py finalize --request phase1.json --token .automation/lock.json \
    --confirmation .automation/confirmation.json
```

**Neither the base nor the branch is an argument any more.** `postflight` measures the diff from
the SHA phase one read off the remote, and `finalize` asks `git ls-remote` what the bound branch
carries. Both used to be strings the caller supplied, and both were the same hole: the step that
judges the work also chose what to judge. `--base` still exists so that passing one that
disagrees with the token is an error rather than a silent narrowing, and `--pushed-sha` still
exists as a claim the remote is allowed to contradict.

**What ties the five steps into one run is not the order.** An order is a suggestion, and the
agent writes the files. Three things are checked at every step instead:

1. **The remote lock.** Each step re-reads the lock ref and compares it against the token's
   `lock_sha`. A token proves what this run once took; it says nothing about now, and another
   run can delete the ref and take it while that file still looks convincing. Gone, or pointing
   somewhere else, stops the step.
2. **The confirmation artifact.** `postflight` and `finalize` refuse without one bound to the
   same token, so `preflight → postflight` cannot skip the re-read.
3. **The token's own copy of the decision.** The issue body hash, the pull requests, the
   selected revision and the target — remote, branch, base SHA — live in the token. `postflight`
   derives its path policy from a body whose hash matches the confirmed one, so widening
   *Allowed paths* in the request file after phase one gets `BLOCKED_SCOPE` rather than a wider
   diff; and a request that names a different branch or base than the token gets the same.

**A refused `confirm` gives the lock back** and clears the token and marker. Otherwise a
withdrawn label leaves every later run reporting `ALREADY_RUNNING` forever. If the release
itself fails, the report carries both the original refusal and the release failure.

**The revision is recorded by `finalize`, never earlier.** `finalize` asks the remote what the
bound branch carries and requires it to equal the commit `postflight` verified, and only then
writes the applied id to durable state. Recording before the push means a failed push leaves
"already applied" true while the fix exists nowhere. A branch that does not exist, one carrying
a different commit, and the verified commit sitting on some *other* branch are all
`BLOCKED_SCOPE`, and all leave the token in place so the run can be retried.

**A `finalize` whose release fails is not a finished run.** It exits non-zero, keeps the token
and confirmation so `release` can retry, and prints the `git push --force-with-lease` line that
clears the ref by hand. Exit 0 with the lock still held would strand every later run on
`ALREADY_RUNNING` after deleting the artifacts needed to free it. Re-running `finalize` is safe:
recording an already-recorded revision is a no-op, and the remote check is unchanged.

**There is no default lock.** A request whose `lock` field is missing, misspelled, or names
`file`/`memory` is `INVALID_SPEC` — the store used to fall back to an in-process one, which for
a scheduled run (one container each) is not a weaker lock but no lock at all, reported in every
line of output as though it were real. `--development` permits the local stores for tests, and
a scheduled run must never pass it. The same applies to `state`: if any approved revision is in
play and no durable state store is configured, `preflight` refuses **before** taking the lock,
because the alternative is discovering it after the push, when the work has already been done
twice.

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
  "workdir": ".",
  "target": {
    "remote": "origin",
    "branch": "claude/vcrp-ops-002-thing",
    "base_branch": "main",
    "repository": "Dracloud-sys/Virtual-Cell-Reasoning-Platform"
  },
  "lock":  {"kind": "git-ref", "remote": "origin", "workdir": "."},
  "state": {"kind": "git-ref", "remote": "origin", "workdir": "."}
}
```

- **`queue_error`** is for the case where the query *failed*. Never pass an empty page list to
  represent a failure. A REST error envelope (`{"message": "Bad credentials", "status": "401"}`)
  is also refused, because it carries no `issues` collection at all.
- **Every page** goes in `queue_pages`. If the last page says `hasNextPage`, the read is
  refused: one issue plus "there is more" would dispatch work while a second approved issue sat
  unseen on page two.
- **`approvals`** are the raw review payloads. The parser derives the record id, author login,
  body, pull request and full commit id from GitHub's own fields; an `approved_by` written
  beside them is ignored.
- **A request may not name its approvers.** `approvers` or `approvers_file` in the request is a
  **schema error**, not an ignored field — the agent writes the request, so a list it can point
  at is a list it can write. They come from [`run_approvers.json`](run_approvers.json), which
  changes only by a reviewed commit, and an empty list approves nobody.
- **`target`** is read once, by `preflight`, and then frozen into the token. `base_branch` is
  resolved on the remote — not from the container's `origin/main`, which may be days old — and
  stored as a full 40-character SHA that must already be present locally, or the run is
  `BLOCKED_ENVIRONMENT` with "fetch the base first". The branch must belong to this work item.
  Later steps may repeat these fields, but not change them: a mismatch is `BLOCKED_SCOPE`.
- **`applied_revision_ids`** may not be stated in the request outside `--development`. Which
  revisions have been carried out is a fact the durable state store keeps, not one the agent
  asserts.

### `captured_at` is an assertion, not evidence

Say this plainly, because it would be easy to read the freshness check as stronger than it is.
`captured_at` is **a string the calling agent writes**. It asserts that the responses were
gathered after the lock was taken; it does not prove it, and nothing in this repository can make
it prove it.

What is actually checked is two weaker things:

- the asserted timestamp postdates the lock — which catches an honest agent replaying an old
  file, and catches nothing else;
- the phase-two file's own mtime postdates the lock — which catches a file prepared in advance,
  and is still only a local filesystem fact.

Closing this properly needs a server-side timestamp from the GitHub response itself, or a tool
call record the agent does not author. Until then, treat the two-phase protocol as protection
against *mistakes and races*, not against a determined caller.

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
| `INVALID_SPEC` | a section is missing, unfilled, placeholder-filled, or self-contradictory; or the request configures no `git-ref` lock, no `target`, or no state store for a revision it would apply | fix the issue body, or the request — the report names what is missing. A missing lock is never downgraded to a local one |
| `WORK_ID_MISMATCH` | the issue declares a different work id | fix whichever is wrong. The **issue** is authoritative |
| `BLOCKED_GITHUB_ACCESS` | the query failed, or the lock store was unreachable | check repository access on the Routine first — this is never read as an empty queue |
| `BLOCKED_ENVIRONMENT` | interpreter below 3.12, or dependencies missing | fix the environment's setup script; do not hand-install and re-run, or the next run breaks the same way |
| `ALREADY_RUNNING` | another run holds the lock | wait, or follow *Recovery* below if nothing is actually running |
| `AWAITING_REVIEW` | a pull request for this work is open | review it. A second branch for the same issue is a fork, not progress |
| `AMBIGUOUS_PULL_REQUEST` | two open pull requests claim this work id | close or retarget one. The run will not pick |
| `BLOCKED_SCOPE` | a needed change is outside the issue's allowed paths, a later step named a different base or branch than the token, or the remote does not carry the commit that was verified | widen the issue deliberately, or split the work — never the diff. From `finalize`, check whether the push actually landed on the bound branch |

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
run does not need this. Only a killed process does — and one other case: a `finalize` whose
work landed but whose release failed. That one exits non-zero, keeps the token on purpose, and
prints the exact `--force-with-lease` line for step 4; retrying `finalize` or `release` is the
first thing to try, because both are safe to repeat.

`FileLockStore` is refused outside `--development`, so a scheduled run cannot end up holding a
lock nobody else can see. If a run reports `INVALID_SPEC` naming the lock, the request is
missing its `lock` block — that is the fix, not a flag.

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
