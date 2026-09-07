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

# ...then query the pull requests AGAIN and write completion.json...

# after the push - ask the remote what the branch carries, check the deliverable, record, release
python scripts/automation/cli.py finalize --request phase1.json --token .automation/lock.json \
    --confirmation .automation/confirmation.json --completion .automation/completion.json
```

**The repository is not a request field at all.** Which repository, which remote, which base
branch and which refs come from [`run_target.json`](run_target.json), committed for the same
reason the approver list is. Reading the base "off the remote" proves nothing if the caller
picked the remote — and before this, `target.remote`, `lock.remote` and `state.remote` were all
the agent's to write. A request may **repeat** those values; a request that differs from them is
a schema error. `preflight` also checks, before taking the lock, that `git remote get-url origin`
in this checkout really is the configured repository.

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

**A pushed branch is not the deliverable.** The Routine's output is a **draft pull request
targeting `main`**, so `finalize` takes `--completion`: the pull request listing, queried again
after the push. It must show exactly one open pull request for this work item, `draft: true`,
from the bound branch, at the commit `postflight` verified, targeting the configured base — and,
on a revision run, the pull request the approved instruction was written on. Anything else
refuses **without recording or releasing anything**: the run is unfinished rather than finished
badly, so open or fix the pull request and run `finalize` again.

That last clause is not a nicety. On the revision path, pushing the changes to a second
`claude/<work-id>-*` branch and recording the instruction as applied would retire it while the
pull request its author is reading stayed exactly as it was.

**A `finalize` whose release fails is not a finished run.** It exits non-zero, keeps the token
and confirmation so `release` can retry, and points at the runbook's tombstone procedure. Exit 0 with the lock still held would strand every later run on
`ALREADY_RUNNING` after deleting the artifacts needed to free it. Re-running `finalize` is safe:
recording an already-recorded revision is a no-op, and the remote check is unchanged.

**There is no default lock, and no request-chosen one.** In production both stores are built
from `run_target.json`; under `--development` a request supplies them itself, and a `lock` field
that is missing, misspelled, or names `file`/`memory` without the flag is `INVALID_SPEC`. The
store used to fall back to an in-process one, which for a scheduled run (one container each) is
not a weaker lock but no lock at all, reported in every line of output as though it were real. A
scheduled run must never pass `--development`. A request may also never state
`applied_revision_ids`: "this was already done" is the one answer that makes a run skip work, so
it comes from the durable store or not at all.

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
  "target": {"branch": "claude/vcrp-ops-002-thing"}
}
```

and `completion.json`, written after the push and read only by `finalize`:

```json
{
  "captured_at": "2026-09-06T06:20:00+00:00",
  "pull_requests": [ "<raw list_pull_requests response, queried after the push>" ]
}
```

- **`queue_error`** is for the case where the query *failed*. Never pass an empty page list to
  represent a failure. A REST error envelope (`{"message": "Bad credentials", "status": "401"}`)
  is also refused, because it carries no `issues` collection at all.
- **Every page** goes in `queue_pages`. If the last page says `hasNextPage`, the read is
  refused: one issue plus "there is more" would dispatch work while a second approved issue sat
  unseen on page two.
- **`totalCount` is checked against what was supplied.** Every page states how many issues the
  *query* matched, and the same number on each page of one read. If the pages hand over fewer
  issues than that number claims, the read is refused as incomplete rather than acted on. This
  is what separates "the queue is empty" from "the listing came back empty" — the second is a
  failed read wearing the first one's clothes, and the difference decides whether a night of
  silence was a quiet night or a broken one. A genuinely empty queue is one page, `issues: []`,
  `totalCount: 0`; that is the only shape that means nothing is approved.
- **On a quiet night, the request is only the queue.** `preflight` asks the queue **before** it
  asks anything else — before the target, the branch snapshot, the approvers, the state store
  and the lock. All of those are questions about *the work*, and when nothing is approved there
  is no work to ask them about: no issue means no work id, and no work id means no branch to
  name after it. So a run whose queue read came back empty writes exactly this and nothing more:

  ```json
  {
    "queue_pages": [ "<the raw list_issues response>" ],
    "queue_error": null,
    "workdir": "."
  }
  ```

  and `preflight` exits **10 `NO_READY_WORK`**, having consulted no remote, read no approvers
  file, touched no lock and written no token. Do **not** invent a work id or a branch name to
  get past a schema check; a made-up identifier in a run record is worse than a missing one.
  The bullets below apply from one approved issue onward.
- **`existing_branches` must be stated, even when it is empty.** It is the branches that already
  exist for this work item, and `[]` is a real answer — somebody looked and there were none. An
  *absent* key is not: it reads as the same empty list, which would hide a crashed run's leftover
  branch and let this run open a second branch, and then a second pull request, for one issue.
  Phase one refuses `INVALID_SPEC` without it. Phase two refuses `BLOCKED_GITHUB_ACCESS` without
  it, for a different reason: the whole point of the re-read is to show what appeared while the
  lock was being taken, and a re-read that omits the snapshot cannot show that.
- **`approvals`** are the raw review payloads. The parser derives the record id, author login,
  body, pull request and full commit id from GitHub's own fields; an `approved_by` written
  beside them is ignored.
- **A request may not name its approvers.** `approvers` or `approvers_file` in the request is a
  **schema error**, not an ignored field — the agent writes the request, so a list it can point
  at is a list it can write. They come from [`run_approvers.json`](run_approvers.json), which
  changes only by a reviewed commit, and an empty list approves nobody.
- **`target.branch`** is the only part of the target a request supplies, and it must begin with
  the configured prefix and this work id. Everything else — remote, base branch, repository, the
  lock namespace, the state ref — comes from `run_target.json`; stating a *different* value is a
  schema error, and stating the same value is allowed. `preflight` resolves `base_branch` on the
  remote (not from the container's `origin/main`, which may be days old), stores the full
  40-character SHA in the token, and refuses with `BLOCKED_ENVIRONMENT` if this checkout does not
  already have that commit. Later steps may repeat the target's fields, but not change them: a
  mismatch is `BLOCKED_SCOPE`.
- **`pull_requests` in `completion.json`** must carry `draft` for every entry. A listing that
  omits it is refused rather than guessed: assuming `true` completes a run that published a
  ready-for-review pull request, and assuming `false` refuses every correct run.
- **`applied_revision_ids`** may never be stated in a request, `--development` included. Which
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

**The queue is asked first, and its answer is final for that run.** This ordering is the
contract, not an optimisation. `NO_READY_WORK` is the status the whole package exists to keep
distinct from a malfunction, and it is worthless if a correct quiet run can be answered
`INVALID_SPEC` instead because it had no issue to take a work id from. The three answers below
the table — a failed query, an incomplete read, a `queue_error` — are `BLOCKED_GITHUB_ACCESS`,
and none of them is ever downgraded to "0 issues".

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
| `AMBIGUOUS_PULL_REQUEST` | two open pull requests claim this work id, at the start or at completion | close or retarget one. The run will not pick |
| `BLOCKED_SCOPE` | a needed change is outside the issue's allowed paths; a later step named a different base or branch than the token; the remote does not carry the commit that was verified; or the deliverable is missing, not a draft, on the wrong branch, at the wrong commit, or targeting the wrong base | widen the issue deliberately, or split the work — never the diff. From `finalize`, check whether the push landed on the bound branch and whether the draft pull request exists; then run `finalize` again |

## Revising a pull request that is under review

The default is that a run may not touch it. The exception needs all four of:

1. an **approval record id** — the GitHub review or comment the instruction came from;
2. an **approver on the committed list** in `run_approvers.json`; a name the agent writes into
   its own request is a string, not an approval, and an empty list approves nobody;
3. the **full 40-character head SHA** the instruction was written against. Once the branch
   moves the instruction has expired: the same sentence is now a request about code its author
   has not read. Abbreviations are refused rather than prefix-matched;
4. **not already applied.** Applied ids live in a git ref
   (`refs/heads/vcrp-automation/state/applied-revisions`),
   so a restarted run reads what its predecessor did instead of doing it again. That store is
   fail-closed: a ref that does not exist yet is an empty set, but a ref that could not be
   *reached* blocks the run. Reading "nothing has been applied" out of a failed fetch is exactly
   how an approved revision gets carried out twice.

Anything that fails these is reported in the `AWAITING_REVIEW` detail — passed over, never
silently ignored.

**Updating an already-open pull request is the revision path's privilege, and nothing else's.**
`finalize` refuses `BLOCKED_SCOPE` when a run carrying no approved revision instruction finishes
on a pull request that was already open when phase one decided — the token records the numbers
it saw, so this is checked against phase one's reading rather than against the completion
payload's account of itself. On a revision run the deliverable must be *exactly* the pull request
the bound instruction was written on; recording the instruction as applied against any other one
retires it falsely.

This is a second gate, deliberately. `preflight` already refuses `AWAITING_REVIEW` when an open
pull request for the work item has no actionable revision, so nothing should reach `finalize` in
that shape. The two refusals answer to different evidence — the queue read, then the token — and
the cost of the check being wrong is a reviewer's pull request rewritten under them.

## Re-running

A run is safe to repeat. It reads the queue again, re-validates the spec, and stops in the same
place unless the cause is gone.

1. Fix the cause the status names.
2. Trigger the Routine (**Run now**), or wait for the schedule.
3. Confirm the outcome in the run record comment and the exit code — **not** in the run's green
   status. A green run status means the container exited cleanly, which is also what a
   completely blocked run does.

## Recovery after a crash

A run that dies between taking the lock and finishing leaves the lock `active`, and every later
run reports `ALREADY_RUNNING`.

**There is no delete step, and there must not be one.** This execution environment refuses ref
deletion outright — `git push --delete`, with or without a lease, comes back HTTP 403 — so a
recovery procedure built on deleting the lock is a procedure that cannot be run when it is
needed. Recovery is the same transition a normal release makes: `active` → `tombstone`.

1. Confirm nothing is running: check the Routine's run list for an in-flight session.
2. Read the lock:

   ```bash
   git ls-remote origin 'refs/heads/vcrp-automation/locks/*'
   git fetch origin '+refs/heads/vcrp-automation/locks/<work-id>:refs/vcrp-peek'
   git show refs/vcrp-peek:lock.json     # owner, generation, acquired_at, nonce
   ```

3. **Prefer the token.** If `.automation/lock.json` survived, `release` makes the transition
   with a compare-and-swap and no override is needed. The token is on disk precisely so the
   process that gives the lock back need not be the one that took it.
4. If the token is gone, write the tombstone by hand from the **exact** active SHA:

   ```bash
   REF=refs/heads/vcrp-automation/locks/<work-id>
   ACTIVE=$(git ls-remote origin "$REF" | cut -f1)
   # take lock.json from the active commit, set state/released_at/previous, keep the rest
   git show "$ACTIVE:lock.json" | python3 -c 'import json,sys,datetime;\
     r=json.load(sys.stdin); r["state"]="tombstone"; r["previous"]=sys.argv[1];\
     r["released_at"]=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds");\
     r["release_nonce"]="manual-recovery";\
     print(json.dumps(r, indent=2, sort_keys=True))' "$ACTIVE" > /tmp/lock.json
   BLOB=$(git hash-object -w /tmp/lock.json)
   TREE=$(printf '100644 blob %s\tlock.json\n' "$BLOB" | git mktree)
   TOMB=$(git commit-tree "$TREE" -p "$ACTIVE" -m "tombstone <work-id> (manual recovery)")
   git push --force-with-lease="$REF:$ACTIVE" origin "$TOMB:$REF"
   git ls-remote origin "$REF"           # must now be $TOMB
   git fetch origin "+$REF:refs/vcrp-peek" && git show refs/vcrp-peek:lock.json | grep tombstone
   ```

   The lease on `$ACTIVE` is what makes this safe: if a live run took the lock in the meantime,
   the push is rejected rather than stealing it. **Never overwrite the lock with an arbitrary
   SHA, and never force without a lease** — those are the two ways to retire a lock a running
   process still believes it holds.
5. Clear the stale token and confirmation files from the dead run's workspace, if any survived.
6. Check for a half-pushed branch: `git ls-remote --heads origin 'claude/*'`. A branch with no
   pull request is a crashed run's leftovers. The next run reports it as `resume_branch` and
   continues on it rather than opening a second one.
7. Re-run.

The gate makes this transition itself on every refusal that happens after the lock was taken, so
a blocked run does not need any of the above. Only a killed process does — and one other case: a
`finalize` whose work landed but whose release failed. That one exits non-zero and keeps the
token on purpose; retrying `finalize` or `release` is the first thing to try, because both are
safe to repeat.

`FileLockStore` is refused outside `--development`, so a scheduled run cannot end up holding a
lock nobody else can see.

## Concurrency

The lock is a **state machine in a ref**, not a ref's existence. `refs/heads/vcrp-automation/
locks/<work-id>` is created once and then lives forever, alternating between two records stored
as `lock.json` inside the commit:

| field | why it is there |
|---|---|
| `schema` | `vcrp-lock/1`. A reader that does not know it refuses rather than guesses |
| `state` | `active` or `tombstone`. Nothing is decided by matching words in a commit message |
| `work_id`, `owner`, `nonce` | who holds it, and what makes this commit unlike any other |
| `generation` | monotonic. A token from generation 3 cannot retire generation 4's lock |
| `acquired_at`, `released_at` | when |
| `previous`, `release_nonce` | which record this one replaced, and whose release it was |

**Acquire.** The ref absent → build an `active` record and push it; the ref holding a tombstone →
build an `active` record parented on that tombstone and push under a lease on its SHA; the ref
holding an `active` record → somebody else is running, `ALREADY_RUNNING`. In both writing cases
a contender that read the same starting point loses the compare-and-swap, and exactly one wins.

**Release.** Read the remote, require it to still be this run's exact `active` commit, build a
tombstone parented on it, push under a lease on that SHA.

Two findings from the real remote shaped this, and both are recorded here because both were
first believed to be working:

- **`refs/vcrp-locks/*` and `refs/vcrp-state/*` cannot be written at all.** Creating either is
  refused with HTTP 403 on `git-receive-pack` in this execution environment, while creating and
  updating a branch succeeds. That is why the automation state lives under `refs/heads/` — and
  why `run_target.json` names it, so moving it again is a one-line reviewed commit.
- **Ref deletion is refused too**, which is why release is a transition. The refused delete
  returned `Everything up-to-date` on stdout **and exit code 0**, so no write in the store is
  believed on its exit code: every one is followed by re-reading the remote with `ls-remote`,
  and a release additionally re-reads the object and requires it to parse as a tombstone. The
  same rule applies to the state store: a recording counts only when the remote's `applied.json`
  actually contains the identifier.

An older hole, kept because its shape recurs: git objects are content-addressed, so two runs
with the same work id, owner and one-second timestamp once built the **same commit** and both
concluded they held the lock — `[True, True]`. Every `active` record carries a per-run nonce and
every tombstone a per-release nonce, which is what makes two contenders' commits distinct.

Three distinctions the store refuses to blur:

- **rejected is not failed.** A rejected push means somebody else got there first. A push that
  failed for any other reason raises `LockUnavailable`, which the gate reports as
  `BLOCKED_GITHUB_ACCESS`. Treating an unreachable remote as a free lock would be the worst
  available reading.
- **unparseable is not free.** A `lock.json` that does not parse, carries an unknown schema, or
  names a state that is neither, raises `LockCorrupt` — never "nobody holds it".
- **holding is not owning.** A release moves only the exact `active` commit this run took.

`tests/automation/test_gitref_lock.py` races six threads through one barrier against one bare
repository — from an absent ref *and* from a shared tombstone — and asserts exactly one comes
back holding it. It also reproduces the 403-shaped liar (HTTP 403 in stderr, "Everything
up-to-date" on stdout, exit 0) and requires the release to fail.

`FileLockStore` remains for a single container (two processes, one filesystem). It cannot see a
run in another container and must not be used for the scheduled path.

### These refs are not work branches

`refs/heads/vcrp-automation/*` holds automation state that happens to live under `refs/heads/`
because nothing else is writable. Nothing is ever merged from it, and no pull request is opened
against it. CI does not run on it either: `.github/workflows/ci.yml` triggers on `push` to
`main` and `pull_request` targeting `main`, and pushing two probe refs under this namespace on
the real origin produced **no workflow run** (run count unchanged, measured before and after).

## The run record

**Every run posts one, including a run that changed nothing.** Nothing outside the container can
read the run's transcript, so a run that reports only into its own session leaves no evidence it
happened — which is how three consecutive scheduled runs "succeeded" while doing nothing at all
and stayed invisible for a day.

The record goes on
[issue #21](https://github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform/issues/21), as a
comment, via `add_issue_comment`. That issue is open on purpose and is both the log and the v1
cutover checklist. It replaces the earlier use of closed meta issue #18.

```
## Run record

| | |
|---|---|
| finished (UTC) | <timestamp> |
| status | <READY_FOR_GPT_REVIEW / BLOCKED / NO_READY_WORK / AMBIGUOUS_QUEUE> |
| queue tool | <the exact tool name used for the claude-ready query> |
| queue result | <the raw result, e.g. totalCount 0, issues []> |
| gate steps | <each command run and its exit code> |
| repo changes | <branch + PR, or "none"> |

<one short paragraph: what you did, or why there was nothing to do>
```

Never add `claude-ready` to issue #21 and never close it. The label is the work queue: a
non-work item in it makes the next run report `AMBIGUOUS_QUEUE`, and a closed issue is a poor
place to keep sending a log.

If `add_issue_comment` is unavailable, that is a **finding to report**, not an obstacle to route
around. Do not improvise a substitute, and in particular do not create a branch or a file to
carry the record — a log written where the log is not kept is worse than a missing one.

## Routine settings

Changed only as far as this work item needed. **Model and cadence are unchanged.**

| Setting | Before | After |
|---|---|---|
| Schedule | `0 16 * * *` UTC (01:00 KST) | unchanged |
| Model | `claude-opus-5` | unchanged |
| Enabled | `false` | `false` — re-enabling needs explicit approval |
| Repositories | none attached | `Dracloud-sys/Virtual-Cell-Reasoning-Platform` |
| Prompt | reported only into its own session | the five-step contract: `preflight` → re-query → `confirm` → implement + `postflight` → push, draft pull request, re-query → `finalize`, then a run record comment |

The repository attachment was the defect behind three empty runs: with no source attached the
container cloned nothing, so the run could not read `CLAUDE.md`, could not query the queue, and
could not have opened a pull request. It was diagnosed by the absence of a run record, which is
why the record exists.

### Where the run pushes — and what actually stops it

An earlier version of this section told the reader to open two fields in the Routines UI and
change them. **Those fields do not exist.** The Routines edit form covers the name, prompt,
repositories, environment, connectors and triggers — nothing else. `outcome_branch` and
`allowed_push_branches` are session configuration the backend fills in; they appear in the
Routines API's *read* of a trigger and are settable by neither the API nor the UI. A procedure
for changing them was a procedure nobody could follow, and it sat here reading like a control we
had.

**What the platform actually enforces** (Claude Code Routines, *Repositories and branch
permissions*): a branch prefixed `claude/` is always accepted. A push to any other branch is
checked first and refused when **any** of these holds:

1. the branch is protected on GitHub;
2. someone else has an open pull request from that branch;
3. the branch carries commits authored by someone other than the account the Routine runs as.

Read against this repository:

| Destination | Rule that applies | Result |
|---|---|---|
| `claude/<work-id>-<name>` | `claude/` prefix | always accepted — this is the deliverable's branch |
| `vcrp-automation/locks/*`, `vcrp-automation/state/*` | the three checks | accepted: unprotected, no foreign pull request, our own commits. Matches the real probe |
| **`main`** | the three checks | **the gap.** Unprotected until it was protected, no pull request from it, and its commits are authored by the same account the Routine runs as — so all three passed and nothing refused the push |

**So the guard is GitHub branch protection on `main`, and nothing else is.** That is a stronger
control than the setting we thought we were configuring, because it binds every actor rather
than one Routine, and it is the *first* condition the platform's own check consults. It is set
on GitHub — **Settings → Rules → Rulesets** — not on claude.ai.

### The ruleset, as it stands

| | |
|---|---|
| id | `22420277` |
| name | `protect-main` |
| enforcement | `active` |
| target | `~DEFAULT_BRANCH` |
| bypass actors | **none** |
| current user can bypass | **never** |

Rules on it:

| Rule | Why it matters here |
|---|---|
| pull request required | **the one that closes the gap.** It refuses the direct push itself |
| required approvals `0` | the direct push is refused at any value; `0` keeps ordinary review-and-merge working |
| required status check `test` | the gate must be green before anything reaches `main` |
| deletion restriction | `main` cannot be deleted |
| non-fast-forward restriction | `main` cannot be rewritten |

No lock or read-only rule is set, so the branch is normal in every other respect.

**`protected: true` is not by itself the guard.** A ruleset carrying only the creation defaults —
deletion and non-fast-forward restrictions — reports `protected: true` while an ordinary
fast-forward push to `main` still succeeds. *Pull request required* is the rule that refuses the
push, and *bypass actors: none* is what makes it apply to the account the Routine runs as. Both
are read from the ruleset itself rather than inferred from the branch's `protected` flag, which
is why the id is recorded above: a later reader can re-read the same object rather than trust
this table.

### The outcome branch: unmodifiable backend metadata

The Routine's stored configuration carries
`outcomes[].git_repository.git_info.branches: ["claude/fervent-clarke"]`, a harness-generated
name from before this contract existed. **There is no way to clear it.** It is not in the edit
form, `update_trigger` cannot write it, and `create_trigger` has no such parameter — so even
deleting and recreating the Routine, which would destroy its run history, could not set it.

Record it as **backend metadata, not a setting**: it is a fact about the Routine to be aware of,
not an item anyone can action. What can be said about its risk is bounded and checkable:

- it is `claude/`-prefixed, so it names a branch inside the always-accepted namespace and cannot
  reach `main` or anything protected;
- no such branch exists on origin, so nothing has ever been pushed to it;
- whether a firing *creates* it is a question with an answer, and the empty-queue smoke test is
  where that answer is taken: after **Run now** on an empty queue, `git ls-remote --heads origin`
  must still show no `claude/fervent-clarke`. If it appears, the harness pushes to the outcome
  branch on its own and that is a finding — a second destination for a run's work that the token
  never bound and `finalize` never checks.

### The smoke test, with the Routine still disabled

**Run now** fires without enabling the schedule, which is what makes this provable beforehand
rather than something to watch afterwards. Run it once against an empty queue and check:

1. the gate exited **10**;
2. `git ls-remote origin` is unchanged — no new branch, no new ref;
3. **no `claude/fervent-clarke`** (the outcome-branch question above);
4. no pull request was opened;
5. a run record appeared on issue #21.

A quiet night is the cheapest end-to-end proof of the scheduled path, and it is exactly what the
three "successful" empty runs looked like from the outside. The difference is the record.

Do not delete and recreate the Routine to change any of this. That loses its run history — the
only record of the three empty runs — and buys nothing: the two fields are unsettable at
creation time as well.

**Re-enabling the schedule is not part of this work item.** A run driven by hand proves the
gate; it does not prove the scheduled path end to end. The conditions live on
[issue #21](https://github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform/issues/21), in three
groups, and the split matters:

| Group | What it is | Relation to the switch |
|---|---|---|
| **Pre-enable gates** | everything provable while the Routine is off | all must pass **before** enabling |
| **Post-enable probation** | the first real scheduled firings | observed **after** enabling; a failure means disable again, same day |
| **Follow-up** | housekeeping and the two remaining observations | neither blocks nor follows the switch |

A scheduled run cannot happen while the schedule is off, so "one scheduled run completes" was
never a condition for turning it on — it is what turning it on is *for*. Treating it as a
pre-condition made the checklist unsatisfiable, which is worse than a checklist that is merely
long: it reads as caution while making the decision impossible to reach on its own terms.
