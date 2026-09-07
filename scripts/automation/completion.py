"""What "done" means, which is not "the branch is pushed".

`finalize` proved the remote carried the verified commit and then said `work item complete`. But
the Routine's deliverable is a **Draft pull request targeting main**, and a branch with no pull
request is a run that did its work where nobody was asked to look at it. On the revision path it
is worse than incomplete: pushing the changes to a second `claude/<work-id>-*` branch and
recording the approved revision as applied would retire the instruction while the pull request
its author is reading stayed exactly as it was.

So completion is its own set of questions, asked of a **re-queried** pull request payload and
answered against the token rather than against the payload's own claims about itself:

* exactly one open pull request for this work item — none is not done, two is not a choice;
* it is a **draft**, because that is what the Routine is authorised to produce;
* its head branch is the branch phase one bound, not another branch for the same work;
* its head SHA is the commit `postflight` verified, not merely a commit;
* its base is the configured base branch;
* on a revision run, it is the pull request the token's `BoundRevision` names — and on a run
  that is *not* a revision, it is **not** one that was already open at phase one. Updating a
  pull request somebody is already reading is the revision path's privilege, and the revision
  path is the one that required an approval to take.

The head-SHA check is also what makes this evidence rather than assertion: a payload cannot name
a commit that did not exist when it was captured.

Nothing here releases the lock or records anything. A failure means the deliverable is missing
or wrong, the work is still this run's to finish, and the artifacts stay where they are.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .outcomes import Outcome, Status


@dataclass(frozen=True)
class OpenPullRequest:
    """One open pull request, as GitHub describes it."""

    number: int
    head_ref: str
    head_sha: str
    base_ref: str
    draft: bool
    title: str = ""


@dataclass(frozen=True)
class CompletionInputs:
    """The token's idea of the deliverable, and what GitHub says exists."""

    work_id: str
    branch: str
    base_branch: str
    verified_head: str
    pull_requests: Sequence[OpenPullRequest]
    #: Set only on a revision run: the pull request the approved instruction was written on.
    revision_pull_request: int | None = None
    #: The pull requests that were already open when phase one decided, from the token. A run
    #: with no approved revision may not finish on one of these.
    preexisting_pull_requests: frozenset[int] = frozenset()


def _belongs(pull: OpenPullRequest, work_id: str) -> bool:
    """By work id in the branch or the title — never by position in the list."""
    return work_id in pull.head_ref or work_id.lower() in pull.title.lower()


def check_completion(inputs: CompletionInputs) -> Outcome:
    """Whether the deliverable exists, is a draft, and is the one this run was bound to."""
    mine = [pull for pull in inputs.pull_requests if _belongs(pull, inputs.work_id)]
    if not mine:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"{inputs.branch} is pushed and verified, but no open pull request claims "
            f"{inputs.work_id}; a branch nobody was asked to look at is not the deliverable",
            {"branch": inputs.branch},
        )
    if len(mine) > 1:
        numbers = ", ".join(f"#{pull.number}" for pull in mine)
        return Outcome(
            Status.AMBIGUOUS_PULL_REQUEST,
            f"{len(mine)} open pull requests claim {inputs.work_id} ({numbers}); this run will "
            "not decide which one is the deliverable",
            {"pull_requests": numbers},
        )

    pull = mine[0]
    evidence = {"pull_request": str(pull.number), "head": pull.head_sha, "base": pull.base_ref}

    if inputs.revision_pull_request is not None and pull.number != inputs.revision_pull_request:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"the approved revision was written on #{inputs.revision_pull_request} but the open "
            f"pull request for {inputs.work_id} is #{pull.number}; recording the instruction as "
            "applied would retire it against a pull request it was not written for",
            evidence,
        )
    if inputs.revision_pull_request is None and pull.number in inputs.preexisting_pull_requests:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"pull request #{pull.number} was already open when this run started, and this run "
            "carries no approved revision instruction; touching a pull request a reviewer is "
            "already holding is the revision path's privilege, not a new run's",
            evidence,
        )
    if pull.head_ref != inputs.branch:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"pull request #{pull.number} is from {pull.head_ref!r}, but this run is bound to "
            f"{inputs.branch!r}; the work landed somewhere the reviewer is not reading",
            evidence,
        )
    if pull.head_sha != inputs.verified_head:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"pull request #{pull.number} is at {pull.head_sha[:12] or 'nothing'} but "
            f"verification passed on {inputs.verified_head[:12]}",
            evidence,
        )
    if pull.base_ref != inputs.base_branch:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"pull request #{pull.number} targets {pull.base_ref!r}, not {inputs.base_branch!r}",
            evidence,
        )
    if not pull.draft:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"pull request #{pull.number} is not a draft; an unattended run produces a draft for "
            "a person to promote, and promoting it is that person's decision",
            evidence,
        )

    return Outcome(
        Status.READY_TO_IMPLEMENT,
        f"draft pull request #{pull.number} carries {pull.head_sha[:12]} into {pull.base_ref}",
        evidence,
    )
