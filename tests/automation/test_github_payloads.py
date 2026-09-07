"""Reading real responses, where every interesting mistake is the same mistake.

Each case below is a way of mistaking a partial or failed answer for a complete one. They share
a shape: something goes wrong upstream, the response still parses, and the run proceeds on a
picture of the queue that is missing the very thing that should have stopped it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from automation.github_payloads import (
    SchemaError,
    read_open_pull_requests,
    read_pull_requests,
    read_queue,
)

WORK_ID = "vcrp-ops-002"


def _issue(number: int, *, labels=("claude-ready",), state: str = "OPEN", body: str = "x"):
    return {
        "number": number,
        "title": f"[{WORK_ID}] t",
        "body": body,
        "state": state,
        "labels": list(labels),
    }


def _page(issues, *, has_next: bool = False):
    return {"issues": issues, "pageInfo": {"hasNextPage": has_next}, "totalCount": len(issues)}


def test_a_normal_page_reads_as_its_issues() -> None:
    read = read_queue([_page([_issue(21)])])

    assert read.succeeded
    assert [i.number for i in read.issues or ()] == [21]


def test_an_error_is_a_failed_read_not_an_empty_one() -> None:
    read = read_queue([], error="403 Forbidden")

    assert not read.succeeded
    assert read.issues is None
    assert "403" in (read.error or "")


def test_an_error_inside_the_payload_is_also_a_failed_read() -> None:
    read = read_queue([{"error": "rate limited"}])

    assert not read.succeeded
    assert "rate limited" in (read.error or "")


def test_no_response_at_all_is_a_failed_read() -> None:
    """The caller that captured nothing must not be indistinguishable from a quiet queue."""
    read = read_queue([])

    assert not read.succeeded


def test_a_truncated_page_is_a_failed_read_not_a_queue_of_one() -> None:
    """One issue plus 'there is more' would dispatch work while a second approved issue waits."""
    read = read_queue([_page([_issue(21)], has_next=True)])

    assert not read.succeeded
    assert "partial" in (read.error or "")


def test_a_followed_page_completes_the_read() -> None:
    read = read_queue([_page([_issue(21)], has_next=True), _page([_issue(22)])])

    assert read.succeeded
    assert [i.number for i in read.issues or ()] == [21, 22]


def test_a_closed_issue_carrying_the_label_is_not_queued() -> None:
    """Issue #18 is exactly this: labelled, closed, and not work."""
    read = read_queue([_page([_issue(18, state="CLOSED")])])

    assert read.succeeded
    assert read.issues == ()


def test_an_open_issue_without_the_label_is_not_queued() -> None:
    read = read_queue([_page([_issue(21, labels=())])])

    assert read.issues == ()


def test_labels_are_read_whether_they_are_strings_or_objects() -> None:
    as_objects = _issue(21, labels=({"name": "claude-ready"},))
    assert read_queue([_page([as_objects])]).issues != ()


def test_a_different_approval_label_can_be_required() -> None:
    read = read_queue([_page([_issue(21)])], approval_label="approved-for-run")

    assert read.issues == ()


def test_an_issue_without_a_number_fails_the_read_rather_than_being_skipped() -> None:
    read = read_queue([_page([{"title": "t", "state": "OPEN", "labels": ["claude-ready"]}])])

    assert not read.succeeded


def _pr(number: int, ref: str, sha: str, state: str = "open"):
    return {"number": number, "state": state, "title": "t", "head": {"ref": ref, "sha": sha}}


def test_pull_requests_are_matched_by_work_id_not_by_position() -> None:
    payload = [
        _pr(7, "claude/vcrp-ops-999-other", "a" * 40),
        _pr(42, "claude/vcrp-ops-002-gate", "b" * 40),
    ]

    linked = read_pull_requests(payload, work_id=WORK_ID)

    assert [pr.number for pr in linked] == [42]


def test_a_closed_pull_request_is_not_linked() -> None:
    payload = [_pr(42, "claude/vcrp-ops-002-gate", "b" * 40, state="closed")]

    assert read_pull_requests(payload, work_id=WORK_ID) == ()


def test_the_head_sha_is_kept_whole() -> None:
    """A revision instruction is matched against it; an abbreviation is a prefix, not an id."""
    payload = [_pr(42, "claude/vcrp-ops-002-gate", "b" * 40)]

    assert read_pull_requests(payload, work_id=WORK_ID)[0].head_sha == "b" * 40


def test_two_pull_requests_for_one_work_id_are_both_returned() -> None:
    """The gate refuses on two; hiding one here would make that refusal unreachable."""
    payload = [
        _pr(42, "claude/vcrp-ops-002-gate", "b" * 40),
        _pr(43, "claude/vcrp-ops-002-gate-again", "c" * 40),
    ]

    assert len(read_pull_requests(payload, work_id=WORK_ID)) == 2


# --- schema strictness, against captured response shapes ---------------------------------------

_GITHUB = Path(__file__).parent / "fixtures" / "github"


def _fixture(name: str) -> dict:
    return json.loads((_GITHUB / f"{name}.json").read_text(encoding="utf-8"))


def test_the_real_empty_listing_reads_as_an_empty_queue() -> None:
    """Captured from the tool this repository's runs actually call."""
    read = read_queue([_fixture("list_issues_empty")])

    assert read.succeeded
    assert read.issues == ()


def test_the_real_single_issue_listing_reads_as_one_item() -> None:
    read = read_queue([_fixture("list_issues_one")])

    assert read.succeeded
    assert [issue.number for issue in read.issues or ()] == [19]


def test_a_rest_error_envelope_is_a_failed_read() -> None:
    """Regression: this parsed as a healthy empty queue, because it has no `issues` key."""
    read = read_queue([_fixture("rest_error_401")])

    assert not read.succeeded
    assert "Bad credentials" in (read.error or "")
    assert "401" in (read.error or "")


def test_a_graphql_errors_envelope_is_a_failed_read() -> None:
    read = read_queue([_fixture("graphql_errors")])

    assert not read.succeeded
    assert "rate limit" in (read.error or "").lower()


def test_a_response_without_the_issues_collection_is_a_failed_read() -> None:
    read = read_queue([{"pageInfo": {"hasNextPage": False}, "totalCount": 0}])

    assert not read.succeeded
    assert "issues" in (read.error or "")


def test_issues_of_the_wrong_type_fail_the_read() -> None:
    assert not read_queue([{"issues": {"number": 1}}]).succeeded


def test_an_issue_without_a_state_fails_the_read() -> None:
    read = read_queue([_page([{"number": 1, "labels": ["claude-ready"], "title": "t"}])])

    assert not read.succeeded
    assert "state" in (read.error or "")


def test_an_issue_without_labels_fails_the_read() -> None:
    read = read_queue([_page([{"number": 1, "state": "OPEN", "title": "t"}])])

    assert not read.succeeded
    assert "labels" in (read.error or "")


def test_a_boolean_masquerading_as_an_issue_number_fails_the_read() -> None:
    read = read_queue([_page([_issue(21) | {"number": True}])])

    assert not read.succeeded


def test_a_page_that_is_not_an_object_fails_the_read() -> None:
    assert not read_queue([["not", "a", "page"]]).succeeded


def test_an_error_response_where_a_pull_request_list_belongs_raises() -> None:
    with pytest.raises(SchemaError):
        read_pull_requests(_fixture("rest_error_401"), work_id=WORK_ID)


# --- the listing `finalize` judges the deliverable from ---------------------------------------


def _pull(**overrides) -> dict:
    pull = {
        "number": 42,
        "state": "open",
        "draft": True,
        "title": f"[{WORK_ID}] t",
        "head": {"ref": f"claude/{WORK_ID}-gate", "sha": "a" * 40},
        "base": {"ref": "main"},
    }
    pull.update(overrides)
    return pull


def test_an_open_draft_is_read_with_the_fields_completion_is_judged_on() -> None:
    (pull,) = read_open_pull_requests([_pull()])

    assert (pull.number, pull.draft, pull.base_ref) == (42, True, "main")
    assert pull.head_ref.endswith("-gate")


def test_a_listing_that_omits_draft_is_refused_rather_than_guessed() -> None:
    payload = _pull()
    payload.pop("draft")

    with pytest.raises(SchemaError) as raised:
        read_open_pull_requests([payload])

    assert "draft" in str(raised.value)


def test_a_draft_flag_of_the_wrong_type_is_not_a_value() -> None:
    with pytest.raises(SchemaError):
        read_open_pull_requests([_pull(draft="true")])


def test_closed_pull_requests_are_not_the_deliverable() -> None:
    assert read_open_pull_requests([_pull(state="closed")]) == ()


def test_an_error_envelope_where_the_deliverable_belongs_raises() -> None:
    with pytest.raises(SchemaError):
        read_open_pull_requests(_fixture("rest_error_401"))


def test_a_pull_request_with_an_unreadable_head_raises() -> None:
    with pytest.raises(SchemaError):
        read_open_pull_requests([_pull(head="claude/x")])
