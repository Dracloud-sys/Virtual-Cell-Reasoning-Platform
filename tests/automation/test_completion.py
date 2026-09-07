"""What `finalize` accepts as the deliverable, asked directly of the completion check.

`test_full_cycle.py` drives these questions through a real remote, which is where the head SHA
and the pushed branch have to be answered. This file asks the ones that are decisions rather
than measurements — in particular the rule the fifth round added: a run carrying **no** approved
revision may not finish on a pull request that was already open when it started.

That rule is a second gate. `preflight` already refuses `AWAITING_REVIEW` when an open pull
request for the work item has no actionable revision, so today nothing reaches `finalize` in
that shape. It is checked again here because the two refusals answer to different evidence —
preflight's to the queue read, this one to the token — and because the cost of the check being
wrong is a reviewer's pull request rewritten under them by a run nobody approved to touch it.
"""

from __future__ import annotations

import pytest
from automation.completion import CompletionInputs, OpenPullRequest, check_completion
from automation.outcomes import Status

WORK_ID = "vcrp-ops-002"
BRANCH = f"claude/{WORK_ID}-gate"
HEAD = "a" * 40


def _pull(**overrides) -> OpenPullRequest:
    fields = {
        "number": 42,
        "head_ref": BRANCH,
        "head_sha": HEAD,
        "base_ref": "main",
        "draft": True,
        "title": f"[{WORK_ID}] gate",
    }
    fields.update(overrides)
    return OpenPullRequest(**fields)


def _inputs(*, pulls=None, **overrides) -> CompletionInputs:
    fields = {
        "work_id": WORK_ID,
        "branch": BRANCH,
        "base_branch": "main",
        "verified_head": HEAD,
        "pull_requests": [_pull()] if pulls is None else pulls,
    }
    fields.update(overrides)
    return CompletionInputs(**fields)


def test_a_bound_draft_at_the_verified_commit_completes_the_run() -> None:
    outcome = check_completion(_inputs())

    assert outcome.status is Status.READY_TO_IMPLEMENT
    assert outcome.evidence["pull_request"] == "42"


# --- the revision path's privilege ------------------------------------------------------------


def test_a_run_with_no_revision_may_not_finish_on_a_pull_request_it_found_open() -> None:
    """#42 was open at phase one and nothing approved touching it. This run did anyway."""
    outcome = check_completion(_inputs(preexisting_pull_requests=frozenset({42})))

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "already open" in outcome.detail


def test_a_revision_run_may_finish_on_exactly_the_pull_request_it_was_written_on() -> None:
    """The same pull request, the same run — the difference is the approved instruction."""
    outcome = check_completion(
        _inputs(preexisting_pull_requests=frozenset({42}), revision_pull_request=42)
    )

    assert outcome.status is Status.READY_TO_IMPLEMENT


def test_a_pull_request_opened_by_this_run_is_not_a_preexisting_one() -> None:
    """The snapshot names #41; the deliverable is #42, which this run opened."""
    outcome = check_completion(_inputs(preexisting_pull_requests=frozenset({41})))

    assert outcome.status is Status.READY_TO_IMPLEMENT


def test_a_revision_run_is_still_bound_to_its_own_pull_request() -> None:
    outcome = check_completion(
        _inputs(preexisting_pull_requests=frozenset({41}), revision_pull_request=41)
    )

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "#41" in outcome.detail


# --- everything else the deliverable has to be --------------------------------------------------


def test_no_pull_request_at_all_is_not_a_finished_run() -> None:
    assert check_completion(_inputs(pulls=[])).status is Status.BLOCKED_SCOPE


def test_a_pull_request_for_another_work_item_does_not_count_as_this_one() -> None:
    other = _pull(head_ref="claude/vcrp-ops-999-other", title="[vcrp-ops-999] other")

    assert check_completion(_inputs(pulls=[other])).status is Status.BLOCKED_SCOPE


def test_two_pull_requests_for_one_work_item_are_not_a_choice() -> None:
    outcome = check_completion(_inputs(pulls=[_pull(), _pull(number=43)]))

    assert outcome.status is Status.AMBIGUOUS_PULL_REQUEST


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_ref", f"claude/{WORK_ID}-elsewhere"),
        ("head_sha", "b" * 40),
        ("base_ref", "release"),
        ("draft", False),
    ],
)
def test_each_way_the_deliverable_can_be_wrong_is_refused(field: str, value) -> None:
    outcome = check_completion(_inputs(pulls=[_pull(**{field: value})]))

    assert outcome.status is Status.BLOCKED_SCOPE


def test_a_pull_request_is_claimed_by_title_when_the_branch_does_not_say_so() -> None:
    """Belonging is decided by the work id, and a run may have been resumed onto its branch."""
    outcome = check_completion(_inputs(pulls=[_pull(title=f"[{WORK_ID}] gate")]))

    assert outcome.status is Status.READY_TO_IMPLEMENT
