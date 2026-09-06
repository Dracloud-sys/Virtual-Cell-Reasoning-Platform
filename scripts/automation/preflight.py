"""The ordered gate a scheduled run passes before it is allowed to change anything.

The order is part of the contract, not a convenience:

1. **the queue, first.** Reading GitHub is cheap and has no side effects, and everything after
   it is wasted if there is nothing to do. It also means an unreachable API is reported as
   exactly that, before any local state has been touched.
2. **the spec**, because an issue that is not a contract must stop the run whether or not the
   environment would have worked.
3. **an open pull request for this work**, because the reviewer's copy is the deliverable
   until they answer; a second branch for the same issue is not progress, it is a fork.
4. **the lock**, taken only once there is real work to protect.
5. **the environment**, last, because preparing an interpreter for work that does not exist is
   how a quiet night turns into a `BLOCKED_ENVIRONMENT` report about nothing.

Anything that stops the run after the lock was taken gives the lock back. A blocked run that
keeps holding it turns one bad night into every subsequent night reporting `ALREADY_RUNNING`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .environment import EnvironmentFacts
from .locking import LockStore, acquire
from .outcomes import Outcome, Status
from .queue import QueueRead
from .revisions import RevisionInstruction, actionable
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
    owner: str = "scheduled-runner"
    evidence: dict[str, str] = field(default_factory=dict)


def run_preflight(inputs: GateInputs) -> Outcome:
    """Decide whether this run may start, and say precisely why when it may not."""
    queue = inputs.queue

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

    issue = issues[0]
    report = validate_spec(issue.body)
    if not report.ok:
        return Outcome(
            Status.INVALID_SPEC,
            f"issue #{issue.number} is not executable as written: " + " ".join(report.problems),
            {"issue": str(issue.number)},
        )

    revision: RevisionInstruction | None = None
    linked = [pr for pr in inputs.open_pull_requests if pr.work_id == inputs.work_id]
    if linked:
        pull_request = linked[0]
        pending = actionable(
            inputs.revisions,
            pull_request=pull_request.number,
            head_sha=pull_request.head_sha,
            applied_ids=inputs.applied_revision_ids,
        )
        if not pending:
            return Outcome(
                Status.AWAITING_REVIEW,
                f"pull request #{pull_request.number} is open for {inputs.work_id} and has no "
                "approved revision instruction outstanding",
                {"pull_request": str(pull_request.number)},
            )
        revision = pending[0]

    taken = acquire(inputs.lock_store, inputs.work_id, owner=inputs.owner)
    if not taken.proceeds:
        return taken

    if not inputs.environment.fit:
        inputs.lock_store.release(inputs.work_id)
        return Outcome(
            Status.BLOCKED_ENVIRONMENT,
            f"this container cannot run the verification gate: {inputs.environment.summary}",
            {"issue": str(issue.number)},
        )

    evidence = {"issue": str(issue.number), "lock": inputs.work_id}
    if revision is not None:
        evidence |= {
            "revise_pull_request": str(revision.target_pull_request),
            "revision": revision.identifier,
            "reverify": "required",
        }
        detail = (
            f"revising pull request #{revision.target_pull_request} under approved instruction "
            f"{revision.identifier}"
        )
    else:
        detail = f"implementing issue #{issue.number}"

    return Outcome(Status.READY_TO_IMPLEMENT, detail, evidence)
