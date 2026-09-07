"""An approval is a record GitHub wrote, not a field the agent typed.

The previous round accepted `approved_by` and `approval_record_id` as strings in the request
file — and the request file is written by the agent whose work the approval is supposed to
authorise. These tests drive the parser from raw review payloads instead, and fix the two
fail-closed rules: an empty allow-list approves nobody, and a record missing any of its five
load-bearing fields is not an approval.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from automation.approvals import (
    ApproverConfigError,
    load_approvers,
    parse_approvals,
)

APPROVERS = ("Dracloud-sys",)
SHA = "1b716d75d6c0c60eac8930018d75ee184ad36a47"


def _review(**overrides) -> dict:
    payload = {
        "id": 771,
        "user": {"login": "Dracloud-sys"},
        "body": "rename the parser helper",
        "commit_id": SHA,
        "pull_request_url": "https://api.github.com/repos/o/r/pulls/42",
        "state": "APPROVED",
    }
    payload.update(overrides)
    return payload


def test_a_complete_review_becomes_an_instruction() -> None:
    accepted, problems = parse_approvals([_review()], approvers=APPROVERS)

    assert problems == ()
    assert len(accepted) == 1
    instruction = accepted[0]
    assert instruction.approval_record_id == "771"
    assert instruction.approved_by == "Dracloud-sys"
    assert instruction.target_pull_request == 42
    assert instruction.target_head_sha == SHA
    assert instruction.content == "rename the parser helper"


def test_an_empty_approver_list_approves_nobody() -> None:
    """Read as "no restriction", a missing configuration becomes universal authority."""
    with pytest.raises(ApproverConfigError):
        parse_approvals([_review()], approvers=())


def test_an_author_outside_the_list_is_refused() -> None:
    accepted, problems = parse_approvals([_review(user={"login": "drive-by"})], approvers=APPROVERS)

    assert accepted == ()
    assert "not an accepted approver" in str(problems[0])


def test_the_author_comes_from_github_not_from_a_sibling_field() -> None:
    """An `approved_by` the agent supplies is ignored; only `user.login` counts."""
    payload = _review(user={"login": "drive-by"})
    payload["approved_by"] = "Dracloud-sys"

    accepted, problems = parse_approvals([payload], approvers=APPROVERS)

    assert accepted == ()
    assert "drive-by" in str(problems[0])


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("id", "record id"),
        ("body", "no body"),
        ("commit_id", "commit id"),
    ],
)
def test_a_record_missing_a_load_bearing_field_is_not_an_approval(field: str, reason: str) -> None:
    payload = _review()
    payload.pop(field)
    payload.pop("node_id", None)

    accepted, problems = parse_approvals([payload], approvers=APPROVERS)

    assert accepted == ()
    assert reason in str(problems[0])


def test_an_abbreviated_commit_id_is_refused() -> None:
    accepted, problems = parse_approvals([_review(commit_id=SHA[:7])], approvers=APPROVERS)

    assert accepted == ()
    assert "commit id" in str(problems[0])


def test_a_missing_author_object_is_refused() -> None:
    accepted, problems = parse_approvals([_review(user={})], approvers=APPROVERS)

    assert accepted == ()
    assert "author login" in str(problems[0])


def test_a_payload_naming_no_pull_request_is_refused() -> None:
    payload = _review()
    payload.pop("pull_request_url")

    accepted, problems = parse_approvals([payload], approvers=APPROVERS)

    assert accepted == ()
    assert "pull request" in str(problems[0])


def test_a_changes_requested_review_is_not_an_approval() -> None:
    accepted, problems = parse_approvals([_review(state="CHANGES_REQUESTED")], approvers=APPROVERS)

    assert accepted == ()
    assert "not an approval" in str(problems[0])


def test_every_refusal_is_reported_not_silently_dropped() -> None:
    accepted, problems = parse_approvals(
        [_review(user={"login": "drive-by"}), _review(commit_id="short")], approvers=APPROVERS
    )

    assert accepted == ()
    assert len(problems) == 2


def test_the_pull_request_number_is_read_from_the_url_when_absent() -> None:
    accepted, _ = parse_approvals([_review()], approvers=APPROVERS)

    assert accepted[0].target_pull_request == 42


def test_the_committed_approver_list_loads(tmp_path: Path) -> None:
    path = tmp_path / "approvers.json"
    path.write_text(json.dumps({"approvers": ["a", "b"]}), encoding="utf-8")

    assert load_approvers(path) == ("a", "b")


def test_a_missing_approver_file_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ApproverConfigError):
        load_approvers(tmp_path / "absent.json")


def test_an_empty_approver_file_is_a_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / "approvers.json"
    path.write_text(json.dumps({"approvers": []}), encoding="utf-8")

    with pytest.raises(ApproverConfigError):
        load_approvers(path)


def test_the_repositorys_own_approver_list_is_valid() -> None:
    """The file the runner defaults to has to load, or every run is BLOCKED on configuration."""
    root = Path(__file__).resolve().parents[2]
    assert load_approvers(root / "docs/operations/run_approvers.json")
