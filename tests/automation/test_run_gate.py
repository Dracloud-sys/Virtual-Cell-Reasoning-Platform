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
6.  the same work already runs -> at most one run starts
7.  a linked PR awaits review  -> AWAITING_REVIEW, no second branch or PR
8.  an approved revision       -> the same PR is revised and verification re-runs
9.  a revision already applied -> not applied twice
10. a change outside the allowed paths -> BLOCKED_SCOPE   (test_path_scope.py)
"""

from __future__ import annotations

from automation.environment import EnvironmentFacts
from automation.locking import InMemoryLockStore
from automation.outcomes import Status
from automation.preflight import GateInputs, LinkedPullRequest, run_preflight
from automation.queue import QueueIssue, QueueRead
from automation.revisions import RevisionInstruction

WORK_ID = "vcrp-ops-001"

FIT_ENVIRONMENT = EnvironmentFacts(python_version=(3, 12), missing_dependencies=())


def _spec_body(work_id: str = WORK_ID) -> str:
    """A spec that passes validation, so gate tests fail for gate reasons only."""
    return f"""## Work ID

`{work_id}`

## Goal

Prove the gate refuses correctly.

## Work type

- [x] Implementation
- [ ] Investigation-first

## Pre-implementation verification questions

- The ten operational questions in tests/automation.

## Allowed paths

```
scripts/automation/
tests/automation/
```

## Forbidden paths

```
src/virtualcell/
```

## Kernel authorization

- [x] Not authorized
- [ ] Authorized

## Non-goals

No product behaviour changes.

## Stop conditions

Anything needing a scientific judgement.

## Acceptance criteria

- The ten questions pass.

## Biological content change intent

- [x] No biological content changes intended
- [ ] Changes intended

## Interface impact

none - the gate is not reachable from the API, CLI or MCP surface.
"""


def _issue(number: int = 21, work_id: str = WORK_ID) -> QueueIssue:
    return QueueIssue(number=number, title=f"[{work_id}] gate", body=_spec_body(work_id))


def _inputs(**overrides: object) -> GateInputs:
    base: dict[str, object] = {
        "work_id": WORK_ID,
        "queue": QueueRead.ok((_issue(),)),
        "environment": FIT_ENVIRONMENT,
        "lock_store": InMemoryLockStore(),
    }
    base.update(overrides)
    return GateInputs(**base)  # type: ignore[arg-type]


# 1 - an empty queue is a refusal, not a licence to pick something


def test_no_open_approved_issue_reports_no_ready_work() -> None:
    outcome = run_preflight(_inputs(queue=QueueRead.ok(())))

    assert outcome.status is Status.NO_READY_WORK
    assert not outcome.proceeds


# 2 - two ready issues is a refusal to choose, which is the point


def test_two_open_approved_issues_report_ambiguous_queue() -> None:
    outcome = run_preflight(_inputs(queue=QueueRead.ok((_issue(21), _issue(22)))))

    assert outcome.status is Status.AMBIGUOUS_QUEUE
    assert not outcome.proceeds
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


# 6 - concurrency, held by an atomic store rather than by an instruction in a prompt


def test_second_run_of_the_same_work_reports_already_running() -> None:
    store = InMemoryLockStore()

    first = run_preflight(_inputs(lock_store=store))
    second = run_preflight(_inputs(lock_store=store))

    assert first.status is Status.READY_TO_IMPLEMENT
    assert second.status is Status.ALREADY_RUNNING


def test_only_one_of_many_concurrent_runs_starts() -> None:
    store = InMemoryLockStore()

    outcomes = [run_preflight(_inputs(lock_store=store)) for _ in range(5)]

    started = [o for o in outcomes if o.proceeds]
    assert len(started) == 1
    assert all(o.status is Status.ALREADY_RUNNING for o in outcomes if not o.proceeds)


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


# 7 - a PR waiting on a reviewer is not an invitation to open a second one


def test_linked_pull_request_awaiting_review_stops_the_run() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha="abc1234")
    outcome = run_preflight(_inputs(open_pull_requests=(pr,)))

    assert outcome.status is Status.AWAITING_REVIEW
    assert not outcome.proceeds
    assert "42" in outcome.detail


def test_a_pull_request_for_other_work_does_not_stop_this_run() -> None:
    pr = LinkedPullRequest(number=7, work_id="vcrp-ops-999", head_sha="dead123")
    outcome = run_preflight(_inputs(open_pull_requests=(pr,)))

    assert outcome.status is Status.READY_TO_IMPLEMENT


# 8 - an approved revision reopens exactly the PR it names


def test_approved_revision_revises_the_same_pull_request() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha="abc1234")
    revision = RevisionInstruction(
        identifier="comment-9001",
        approved_by="Dracloud-sys",
        target_pull_request=42,
        target_head_sha="abc1234",
    )

    outcome = run_preflight(_inputs(open_pull_requests=(pr,), revisions=(revision,)))

    assert outcome.status is Status.READY_TO_IMPLEMENT
    assert outcome.evidence["revise_pull_request"] == "42"
    assert outcome.evidence["revision"] == "comment-9001"
    # Re-verification is not optional on a revision: the PR's evidence must be regenerated.
    assert outcome.evidence["reverify"] == "required"


def test_revision_for_a_stale_head_does_not_reopen_the_pull_request() -> None:
    """The PR moved on since the instruction was written, so it is no longer that request."""
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha="newhead")
    stale = RevisionInstruction(
        identifier="comment-9001",
        approved_by="Dracloud-sys",
        target_pull_request=42,
        target_head_sha="abc1234",
    )

    outcome = run_preflight(_inputs(open_pull_requests=(pr,), revisions=(stale,)))

    assert outcome.status is Status.AWAITING_REVIEW


def test_unapproved_revision_does_not_reopen_the_pull_request() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha="abc1234")
    unapproved = RevisionInstruction(
        identifier="comment-9002",
        approved_by="",
        target_pull_request=42,
        target_head_sha="abc1234",
    )

    outcome = run_preflight(_inputs(open_pull_requests=(pr,), revisions=(unapproved,)))

    assert outcome.status is Status.AWAITING_REVIEW


# 9 - the same instruction, read again on the next run, must not be applied twice


def test_already_applied_revision_is_not_applied_again() -> None:
    pr = LinkedPullRequest(number=42, work_id=WORK_ID, head_sha="abc1234")
    revision = RevisionInstruction(
        identifier="comment-9001",
        approved_by="Dracloud-sys",
        target_pull_request=42,
        target_head_sha="abc1234",
    )

    outcome = run_preflight(
        _inputs(
            open_pull_requests=(pr,),
            revisions=(revision,),
            applied_revision_ids=frozenset({"comment-9001"}),
        )
    )

    assert outcome.status is Status.AWAITING_REVIEW
    assert not outcome.proceeds
