"""The ordered gate a scheduled run passes before it is allowed to change anything.

The order is part of the contract, not a convenience:

1. **the queue, first.** Reading GitHub is cheap and has no side effects, and everything after
   it is wasted if there is nothing to do. It also means an unreachable API is reported as
   exactly that, before any local state has been touched.
2. **the spec**, because an issue that is not a contract must stop the run whether or not the
   environment would have worked.
3. **identity.** The work id the *issue* declares is the authoritative one. A run told to work
   `vcrp-ops-002` against an issue that says `vcrp-ops-001` would take the wrong lock and look
   for the wrong pull request, so a mismatch stops it rather than being reconciled.
4. **an open pull request for this work**, because the reviewer's copy is the deliverable until
   they answer. Two open pull requests for one work id is a refusal, not a coin toss.
5. **the lock**, taken only once there is real work to protect.
6. **the environment**, last, because preparing an interpreter for work that does not exist is
   how a quiet night turns into a `BLOCKED_ENVIRONMENT` report about nothing.

Anything that stops the run after the lock was taken gives the lock back. A blocked run that
keeps holding it turns one bad night into every subsequent night reporting `ALREADY_RUNNING`.

**Re-reading the world after the lock is not done here**, and the first version's attempt to do
it was the review's sharpest finding: it parsed a second set of responses out of the *same*
request file, which is two snapshots taken before the lock existed wearing a before-and-after
costume. A genuine re-read happens in a later process, after the lock is held, so it lives in
:func:`automation.runner.confirm` — phase two, which is what actually issues permission.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

from .environment import EnvironmentFacts
from .locking import LockStore, acquire
from .outcomes import Outcome, Status
from .queue import QueueRead
from .revisions import RevisionInstruction, actionable, rejections
from .spec_contract import validate_spec


@dataclass(frozen=True)
class LinkedPullRequest:
    """An open pull request, and the work item it belongs to."""

    number: int
    work_id: str
    head_sha: str


@dataclass(frozen=True)
class GateInputs:
    """Everything the gate decides from. No I/O happens in here; callers supply the facts."""

    work_id: str
    queue: QueueRead
    environment: EnvironmentFacts
    lock_store: LockStore
    open_pull_requests: tuple[LinkedPullRequest, ...] = ()
    revisions: tuple[RevisionInstruction, ...] = ()
    applied_revision_ids: frozenset[str] = frozenset()
    approvers: Collection[str] = ()
    #: Branch names that already exist on the remote, so a crashed run's branch is reused
    #: rather than duplicated.
    existing_branches: tuple[str, ...] = ()
    owner: str = "scheduled-runner"
    evidence: dict[str, str] = field(default_factory=dict)


def queue_verdict(queue: QueueRead) -> Outcome | None:
    """The queue's own answer, before anything else about the run is looked at.

    Public because the CLI asks it **first**, ahead of the target, the branch snapshot, the
    approvers and the lock. On a night when nothing is approved there is no issue to take a work
    id from and no work item to name a branch after, so a request that omits both is correct
    rather than malformed — and it used to be answered `INVALID_SPEC`, which reads as "the
    caller wrote a bad file" when the truth is "there was nothing to do".

    One function, two callers, on purpose: a second copy of this ladder in the CLI would be free
    to drift from the one :func:`run_preflight` uses, and the two disagreeing is exactly the
    confusion the exit codes exist to prevent.
    """
    if not queue.succeeded:
        return Outcome(
            Status.BLOCKED_GITHUB_ACCESS,
            f"the approved-work query did not succeed: {queue.error}",
        )
    issues = queue.issues or ()
    if not issues:
        return Outcome(Status.NO_READY_WORK, "no approved issue is open; nothing was changed")
    if len(issues) > 1:
        numbers = ", ".join(f"#{issue.number}" for issue in issues)
        return Outcome(
            Status.AMBIGUOUS_QUEUE,
            f"{len(issues)} approved issues are open ({numbers}); choosing between them is not "
            "this run's decision",
        )
    return None


def _linked(
    pull_requests: tuple[LinkedPullRequest, ...], work_id: str
) -> tuple[LinkedPullRequest | None, Outcome | None]:
    linked = [pr for pr in pull_requests if pr.work_id == work_id]
    if len(linked) > 1:
        numbers = ", ".join(f"#{pr.number}" for pr in linked)
        return None, Outcome(
            Status.AMBIGUOUS_PULL_REQUEST,
            f"{len(linked)} open pull requests claim {work_id} ({numbers}); this run will not "
            "pick one",
            {"pull_requests": numbers},
        )
    return (linked[0] if linked else None), None


def run_preflight(inputs: GateInputs) -> Outcome:
    """Decide whether this run may start, and say precisely why when it may not."""
    refusal = queue_verdict(inputs.queue)
    if refusal is not None:
        return refusal
    issue = (inputs.queue.issues or ())[0]

    report = validate_spec(issue.body)
    if not report.ok:
        return Outcome(
            Status.INVALID_SPEC,
            f"issue #{issue.number} is not executable as written: " + " ".join(report.problems),
            {"issue": str(issue.number)},
        )

    if report.work_id != inputs.work_id:
        return Outcome(
            Status.WORK_ID_MISMATCH,
            f"issue #{issue.number} declares work id {report.work_id!r} but this run was told "
            f"{inputs.work_id!r}; the issue is authoritative",
            {"issue": str(issue.number), "declared": str(report.work_id)},
        )

    pull_request, refusal = _linked(inputs.open_pull_requests, inputs.work_id)
    if refusal is not None:
        return refusal

    revision: RevisionInstruction | None = None
    if pull_request is not None:
        revision, refusal = _revision_for(inputs, pull_request)
        if refusal is not None:
            return refusal

    taken = acquire(inputs.lock_store, inputs.work_id, owner=inputs.owner)
    if not taken.proceeds:
        return taken

    outcome = _after_lock(inputs, issue.number, pull_request, revision, report.kernel_authorized)
    if not outcome.proceeds:
        inputs.lock_store.release(inputs.work_id, inputs.owner)
    return outcome


def _revision_for(
    inputs: GateInputs, pull_request: LinkedPullRequest
) -> tuple[RevisionInstruction | None, Outcome | None]:
    pending = actionable(
        inputs.revisions,
        pull_request=pull_request.number,
        head_sha=pull_request.head_sha,
        applied_ids=inputs.applied_revision_ids,
        approvers=inputs.approvers,
    )
    if pending:
        return pending[0], None

    passed_over = rejections(
        inputs.revisions,
        pull_request=pull_request.number,
        head_sha=pull_request.head_sha,
        applied_ids=inputs.applied_revision_ids,
        approvers=inputs.approvers,
    )
    detail = (
        f"pull request #{pull_request.number} is open for {inputs.work_id} and has no approved "
        "revision instruction outstanding"
    )
    if passed_over:
        detail += "; passed over: " + "; ".join(passed_over)
    return None, Outcome(Status.AWAITING_REVIEW, detail, {"pull_request": str(pull_request.number)})


def _after_lock(
    inputs: GateInputs,
    issue_number: int,
    pull_request: LinkedPullRequest | None,
    revision: RevisionInstruction | None,
    kernel_authorized: bool,
) -> Outcome:
    if not inputs.environment.fit:
        return Outcome(
            Status.BLOCKED_ENVIRONMENT,
            f"this container cannot run the verification gate: {inputs.environment.summary}",
            {"issue": str(issue_number)},
        )

    evidence = {
        "issue": str(issue_number),
        "lock": inputs.work_id,
        "kernel_authorized": "yes" if kernel_authorized else "no",
    }
    resume = [b for b in inputs.existing_branches if b.startswith(f"claude/{inputs.work_id}")]
    if resume:
        # A branch with no pull request is a crashed run's leftovers. Reuse it; a second branch
        # for one issue is how duplicate pull requests get made.
        evidence["resume_branch"] = resume[0]

    if revision is not None:
        evidence |= {
            "revise_pull_request": str(revision.target_pull_request),
            "revision": revision.identifier,
            "approval_record": revision.approval_record_id,
            "reverify": "required",
        }
        detail = (
            f"revising pull request #{revision.target_pull_request} under approved instruction "
            f"{revision.identifier}"
        )
    else:
        detail = f"implementing issue #{issue_number}"

    return Outcome(Status.READY_TO_IMPLEMENT, detail, evidence)
