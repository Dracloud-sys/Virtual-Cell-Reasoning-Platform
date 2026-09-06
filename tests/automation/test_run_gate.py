"""The operational questions the scheduled runner must answer, fixed before it existed.

These are VCRP-OPS-001's benchmark. They are the operational equivalent of a domain
scorecard: each one is a situation the runner will actually meet, and the assertion is what
it must do rather than what it must say. Every case is driven by a fixture or a stubbed
response — never by putting an incomplete issue into the live queue to see what happens,
because a queue used as a test fixture is a queue that can dispatch real work by accident.

The questions, in the order the spec fixes them:

1.  no approved issue          -> NO_READY_WORK, nothing implemented
2.  two or more approved       -> AMBIGUOUS_QUEUE, nothing implemented
3.  blank / placeholder / contradictory spec -> INVALID_SPEC   (test_spec_contract.py)
4.  the GitHub query failed    -> BLOCKED_GITHUB_ACCESS, never read as an empty queue
5.  interpreter or deps unfit  -> BLOCKED_ENVIRONMENT
6.  the same work already runs -> at most one run starts  (test_gitref_lock.py races it)
7.  a linked PR awaits review  -> AWAITING_REVIEW, no second branch or PR
8.  an approved revision       -> the same PR is revised and verification re-runs
9.  a revision already applied -> not applied twice
10. a change outside the allowed paths -> BLOCKED_SCOPE   (test_path_scope.py)

Plus the identity and freshness rules the first review round added: the issue's own work id is
authoritative, two pull requests for one work item is a refusal, and everything read before the
lock is read again after it.
"""

from __future__ import annotations

from pathlib import Path

from automation.environment import EnvironmentFacts
from automation.gitrefs import LockUnavailable
from automation.locking import InMemoryLockStore
from automation.outcomes import Status
from automation.preflight import GateInputs, LinkedPullRequest, run_preflight
from automation.queue import QueueIssue, QueueRead
from automation.revisions import RevisionInstruction

WORK_ID = "vcrp-ops-001"
APPROVERS = ("Dracloud-sys",)
HEAD = "1b716d75d6c0c60eac8930018d75ee184ad36a47"
MOVED_ON = "c8214689efe9bc5ad4e743ac403f9c4ebb7f9a2d"

FIT_ENVIRONMENT = EnvironmentFacts(python_version=(3, 12), missing_dependencies=())


#: Read from a data file rather than duplicated as a literal, so the entry-point test and this
#: one cannot drift into disagreeing about what a valid spec looks like.
_TEMPLATE = (Path(__file__).parent / "fixtures" / "complete_spec.md").read_text(encoding="utf-8")


def _spec_body(work_id: str = WORK_ID) -> str:
    """A spec that passes validation, so gate tests fail for gate reasons only."""
    return _TEMPLATE.format(work_id=work_id)


def _issue(number: int = 21, work_id: str = WORK_ID) -> QueueIssue:
    return QueueIssue(number=number, title=f"[{work_id}] gate", body=_spec_body(work_id))


def _revision(**overrides: object) -> RevisionInstruction:
    base: dict[str, object] = {
        "identifier": "comment-9001",
        "approved_by": "Dracloud-sys",
        "target_pull_request": 42,
        "target_head_sha": HEAD,
        "approval_record_id": "review-771",
        "content": "rename the parser helper",
    }
    base.update(overrides)
    return RevisionInstruction(**base)  # type: ignore[arg-type]


def _inputs(**overrides: object) -> GateInputs:
    base: dict[str, object] = {
        "work_id": WORK_ID,
        "queue": QueueRead.ok((_issue(),)),
        "environment": FIT_ENVIRONMENT,
        "lock_store": InMemoryLockStore(),
        "approvers": APPROVERS,
    }
    base.update(overrides)
    return GateInputs(**base)  # type: ignore[arg-type]


# 1 - an empty queue is a refusal, not a licence to pick something


def test_no_open_approved_issue_reports_no_ready_work() -> None:
    outcome = run_preflight(_inputs(queue=QueueRead.ok(())))

    assert outcome.status is Status.NO_READY_WORK
    assert not outcome.proceeds
    assert outcome.exit_code != 0


# 2 - two ready issues is a refusal to choose, which is the point


def test_two_open_approved_issues_report_ambiguous_queue() -> None:
    outcome = run_preflight(_inputs(queue=QueueRead.ok((_issue(21), _issue(22)))))

    assert outcome.status is Status.AMBIGUOUS_QUEUE
    assert "21" in outcome.detail and "22" in outcome.detail


# 4 - the failure this gate exists to prevent: a 403 that looks like "nothing to do"


def test_failed_github_query_is_not_an_empty_queue() -> None:
    outcome = run_preflight(_inputs(queue=QueueRead.failed("403 from list_issues")))

    assert outcome.status is Status.BLOCKED_GITHUB_ACCESS
    assert outcome.status is not Status.NO_READY_WORK
    assert "403" in outcome.detail


def test_queue_read_cannot_be_both_failed_and_empty() -> None:
    """A failed read carries no issue list at all, so no caller can iterate it as empty."""
    failed = QueueRead.failed("connection reset")

    assert failed.issues is None
    assert not failed.succeeded


def test_every_status_has_its_own_exit_code() -> None:
    """A shell branches on the number; two statuses sharing one would erase the difference."""
    from automation.outcomes import EXIT_CODES

    assert len(set(EXIT_CODES.values())) == len(EXIT_CODES) == len(Status)
    assert EXIT_CODES[Status.READY_TO_IMPLEMENT] == 0
    assert all(
        code != 0 for status, code in EXIT_CODES.items() if status is not Status.READY_TO_IMPLEMENT
    )


# 5 - environment problems are named, never silently worked around


def test_old_interpreter_reports_blocked_environment() -> None:
    outcome = run_preflight(_inputs(environment=EnvironmentFacts(python_version=(3, 11))))

    assert outcome.status is Status.BLOCKED_ENVIRONMENT
    assert "3.11" in outcome.detail


def test_missing_dependency_reports_blocked_environment() -> None:
    unfit = EnvironmentFacts(python_version=(3, 12), missing_dependencies=("pydantic",))
    outcome = run_preflight(_inputs(environment=unfit))

    assert outcome.status is Status.BLOCKED_ENVIRONMENT
    assert "pydantic" in outcome.detail


def test_environment_is_checked_only_after_there_is_work() -> None:
    """Order matters: an empty queue must not be reported as an environment problem."""
    unfit = EnvironmentFacts(python_version=(3, 9), missing_dependencies=("pydantic",))
    outcome = run_preflight(_inputs(queue=QueueRead.ok(()), environment=unfit))

    assert outcome.status is Status.NO_READY_WORK


def test_a_blocked_environment_gives_the_lock_back() -> None:
    """Otherwise one bad night makes every later night report ALREADY_RUNNING."""
    store = InMemoryLockStore()
    run_preflight(_inputs(lock_store=store, environment=EnvironmentFacts(python_version=(3, 11))))

    assert store.holder(WORK_ID) == ""


# 6 - concurrency, held by an atomic store rather than by an instruction in a prompt


def test_second_run_of_the_same_work_reports_already_running() -> None:
    store = InMemoryLockStore()

    first = run_preflight(_inputs(lock_store=store))
    second = run_preflight(_inputs(lock_store=store))

    assert first.status is Status.READY_TO_IMPLEMENT
    assert second.status is Status.ALREADY_RUNNING


def test_a_different_work_id_is_not_blocked_by_another_runs_lock() -> None:
    store = InMemoryLockStore()
    run_preflight(_inputs(lock_store=store))

    other = run_preflight(
        _inputs(
            work_id="vcrp-ops-002",
            queue=QueueRead.ok((_issue(30, "vcrp-ops-002"),)),
            lock_store=store,
        )
    )

    assert other.status is Status.READY_TO_IMPLEMENT


def test_an_unreachable_lock_store_is_not_a_free_lock() -> None:
    """The worst possible reading of "I could not check" is "nobody else is running"."""

    class Unreachable(InMemoryLockStore):
        def create_exclusive(self, key: str, owner: str) -> bool:
            raise LockUnavailable("the lock remote could not be reached: 403")

    outcome = run_preflight(_inputs(lock_store=Unreachable()))

    assert outcome.status is Status.BLOCKED_GITHUB_ACCESS
    assert not outcome.proceeds


# 7 - a PR waiting on a reviewer is not an invitation to open a second one


def test_linked_pull_request_awaiting_review_stops_the_run() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=HEAD)
    outcome = run_preflight(_inputs(open_pull_requests=(pr,)))

    assert outcome.status is Status.AWAITING_REVIEW
    assert "42" in outcome.detail


def test_a_pull_request_for_other_work_does_not_stop_this_run() -> None:
    pr = LinkedPullRequest(number=7, work_id="vcrp-ops-999", head_sha=HEAD)
    outcome = run_preflight(_inputs(open_pull_requests=(pr,)))

    assert outcome.status is Status.READY_TO_IMPLEMENT


def test_two_pull_requests_for_one_work_item_are_refused_not_picked() -> None:
    prs = (
        LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=HEAD),
        LinkedPullRequest(number=43, work_id=WORK_ID, head_sha=MOVED_ON),
    )
    outcome = run_preflight(_inputs(open_pull_requests=prs))

    assert outcome.status is Status.AMBIGUOUS_PULL_REQUEST
    assert "#42" in outcome.detail and "#43" in outcome.detail


def test_an_abandoned_branch_is_reused_rather_than_duplicated() -> None:
    outcome = run_preflight(_inputs(existing_branches=("claude/vcrp-ops-001-run-gate", "main")))

    assert outcome.proceeds
    assert outcome.evidence["resume_branch"] == "claude/vcrp-ops-001-run-gate"


# 8 - an approved revision reopens exactly the PR it names


def test_approved_revision_revises_the_same_pull_request() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=HEAD)
    outcome = run_preflight(_inputs(open_pull_requests=(pr,), revisions=(_revision(),)))

    assert outcome.status is Status.READY_TO_IMPLEMENT
    assert outcome.evidence["revise_pull_request"] == "42"
    assert outcome.evidence["revision"] == "comment-9001"
    assert outcome.evidence["approval_record"] == "review-771"
    # Re-verification is not optional on a revision: the PR's evidence must be regenerated.
    assert outcome.evidence["reverify"] == "required"


def test_revision_for_a_stale_head_does_not_reopen_the_pull_request() -> None:
    """The PR moved on since the instruction was written, so it is no longer that request."""
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=MOVED_ON)
    outcome = run_preflight(_inputs(open_pull_requests=(pr,), revisions=(_revision(),)))

    assert outcome.status is Status.AWAITING_REVIEW
    assert "head that has moved on" in outcome.detail


def test_an_unlisted_approver_cannot_authorise_a_revision() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=HEAD)
    outcome = run_preflight(
        _inputs(open_pull_requests=(pr,), revisions=(_revision(approved_by="drive-by"),))
    )

    assert outcome.status is Status.AWAITING_REVIEW
    assert "not an accepted approver" in outcome.detail


def test_a_revision_without_an_approval_record_is_not_an_approval() -> None:
    """A name typed into a comment is a string; the record id is what can be audited."""
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=HEAD)
    outcome = run_preflight(
        _inputs(open_pull_requests=(pr,), revisions=(_revision(approval_record_id=""),))
    )

    assert outcome.status is Status.AWAITING_REVIEW
    assert "approval record id" in outcome.detail


def test_an_abbreviated_head_sha_is_refused_rather_than_prefix_matched() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=HEAD)
    outcome = run_preflight(
        _inputs(open_pull_requests=(pr,), revisions=(_revision(target_head_sha=HEAD[:7]),))
    )

    assert outcome.status is Status.AWAITING_REVIEW
    assert "full 40-character head SHA" in outcome.detail


# 9 - the same instruction, read again on the next run, must not be applied twice


def test_already_applied_revision_is_not_applied_again() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha=HEAD)
    outcome = run_preflight(
        _inputs(
            open_pull_requests=(pr,),
            revisions=(_revision(),),
            applied_revision_ids=frozenset({"comment-9001"}),
        )
    )

    assert outcome.status is Status.AWAITING_REVIEW
    assert "already applied" in outcome.detail


# identity - the issue's own work id is the authoritative one


def test_a_work_id_the_issue_does_not_declare_is_refused() -> None:
    """A wrong id would take the wrong lock and look for the wrong pull request."""
    outcome = run_preflight(_inputs(work_id="vcrp-ops-002"))

    assert outcome.status is Status.WORK_ID_MISMATCH
    assert "vcrp-ops-001" in outcome.detail and "vcrp-ops-002" in outcome.detail


def test_identity_is_checked_before_the_lock_is_taken() -> None:
    store = InMemoryLockStore()
    run_preflight(_inputs(work_id="vcrp-ops-002", lock_store=store))

    assert store.holder("vcrp-ops-002") == ""
    assert store.holder(WORK_ID) == ""


# freshness lives at the entry point now: a real re-read happens in a later process, so it is
# tested in test_runner_entrypoint.py against the two-phase protocol rather than faked here.
