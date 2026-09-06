"""Reading real responses, where every interesting mistake is the same mistake.

Each case below is a way of mistaking a partial or failed answer for a complete one. They share
a shape: something goes wrong upstream, the response still parses, and the run proceeds on a
picture of the queue that is missing the very thing that should have stopped it.
"""

from __future__ import annotations

from automation.github_payloads import read_pull_requests, read_queue

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
