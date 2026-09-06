"""The entry point, driven the way a scheduled run drives it.

`run_preflight` passing in isolation says the decision is right. It says nothing about whether
the decision is *reachable* from the command the Routine actually invokes, which is where the
first review round found the gap: pure modules and no path from a real response to them.

So these tests call ``python -m automation``'s `main` with a request file holding raw
GitHub-shaped payloads, and assert two things every time — the **exit code**, because that is
what a shell branches on, and the **absence of the proceed marker**, because that is the
observable stand-in for "and then it did not go on to do any work".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from automation.outcomes import EXIT_CODES, Status
from automation.runner import main

WORK_ID = "vcrp-ops-002"
HEAD = "1b716d75d6c0c60eac8930018d75ee184ad36a47"
_TEMPLATE = (Path(__file__).parent / "fixtures" / "complete_spec.md").read_text(encoding="utf-8")


def _issue(number: int = 21, work_id: str = WORK_ID, body: str | None = None) -> dict:
    return {
        "number": number,
        "title": f"[{work_id}] gate",
        "body": _TEMPLATE.format(work_id=work_id) if body is None else body,
        "state": "OPEN",
        "labels": ["claude-ready"],
    }


def _request(tmp_path: Path, **overrides) -> Path:
    payload = {
        "work_id": WORK_ID,
        "approvers": ["Dracloud-sys"],
        "queue_pages": [{"issues": [_issue()], "pageInfo": {"hasNextPage": False}}],
        "lock": {"kind": "file", "directory": str(tmp_path / "locks")},
    }
    payload.update(overrides)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(tmp_path: Path, request: Path, extra: list[str] | None = None) -> tuple[int, Path]:
    marker = tmp_path / "proceeded.json"
    code = main(
        ["preflight", "--request", str(request), "--proceed-marker", str(marker), *(extra or [])]
    )
    return code, marker


def test_a_complete_request_proceeds_and_says_so(tmp_path: Path, capsys) -> None:
    code, marker = _run(tmp_path, _request(tmp_path))

    assert code == 0
    assert marker.exists()
    assert Status.READY_TO_IMPLEMENT.value in capsys.readouterr().out


def test_an_empty_queue_refuses_and_does_no_work(tmp_path: Path) -> None:
    request = _request(tmp_path, queue_pages=[{"issues": [], "pageInfo": {"hasNextPage": False}}])

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.NO_READY_WORK]
    assert not marker.exists()


def test_a_failed_query_refuses_with_its_own_code(tmp_path: Path) -> None:
    request = _request(tmp_path, queue_pages=[], queue_error="403 Forbidden")

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert code != EXIT_CODES[Status.NO_READY_WORK]
    assert not marker.exists()


def test_a_truncated_page_refuses_rather_than_dispatching_one_issue(tmp_path: Path) -> None:
    request = _request(
        tmp_path, queue_pages=[{"issues": [_issue()], "pageInfo": {"hasNextPage": True}}]
    )

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert not marker.exists()


def test_two_approved_issues_refuse_and_do_no_work(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        queue_pages=[{"issues": [_issue(21), _issue(22)], "pageInfo": {"hasNextPage": False}}],
    )

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.AMBIGUOUS_QUEUE]
    assert not marker.exists()


def test_an_unfinished_spec_refuses_and_does_no_work(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        queue_pages=[
            {"issues": [_issue(body="## Goal\n\nTODO\n")], "pageInfo": {"hasNextPage": False}}
        ],
    )

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.INVALID_SPEC]
    assert not marker.exists()


def test_a_work_id_the_issue_does_not_declare_refuses(tmp_path: Path) -> None:
    request = _request(tmp_path, work_id="vcrp-ops-999")

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.WORK_ID_MISMATCH]
    assert not marker.exists()


def test_an_open_pull_request_refuses_and_opens_no_second_one(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        pull_requests=[
            {
                "number": 42,
                "state": "open",
                "title": "t",
                "head": {"ref": f"claude/{WORK_ID}-gate", "sha": HEAD},
            }
        ],
    )

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]
    assert not marker.exists()


def test_an_approved_revision_reopens_the_same_pull_request(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        pull_requests=[
            {
                "number": 42,
                "state": "open",
                "title": "t",
                "head": {"ref": f"claude/{WORK_ID}-gate", "sha": HEAD},
            }
        ],
        revisions=[
            {
                "identifier": "comment-9001",
                "approved_by": "Dracloud-sys",
                "approval_record_id": "review-771",
                "target_pull_request": 42,
                "target_head_sha": HEAD,
                "content": "rename the helper",
            }
        ],
    )

    code, marker = _run(tmp_path, request)

    assert code == 0
    assert json.loads(marker.read_text())["evidence"]["revise_pull_request"] == "42"


def test_the_same_revision_is_not_applied_twice(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        pull_requests=[
            {
                "number": 42,
                "state": "open",
                "title": "t",
                "head": {"ref": f"claude/{WORK_ID}-gate", "sha": HEAD},
            }
        ],
        revisions=[
            {
                "identifier": "comment-9001",
                "approved_by": "Dracloud-sys",
                "approval_record_id": "review-771",
                "target_pull_request": 42,
                "target_head_sha": HEAD,
            }
        ],
        applied_revision_ids=["comment-9001"],
    )

    code, marker = _run(tmp_path, request)

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]
    assert not marker.exists()


def test_a_second_run_while_the_first_holds_the_lock_refuses(tmp_path: Path) -> None:
    request = _request(tmp_path)

    first, _ = _run(tmp_path, request)
    second, _ = _run(tmp_path, request)

    assert first == 0
    assert second == EXIT_CODES[Status.ALREADY_RUNNING]


def test_an_unreadable_request_is_a_blocked_access_not_a_crash(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    code, marker = _run(tmp_path, broken)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert not marker.exists()


def test_json_output_carries_the_status_and_the_code(tmp_path: Path, capsys) -> None:
    code, _ = _run(tmp_path, _request(tmp_path), ["--json"])

    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == Status.READY_TO_IMPLEMENT.value
    assert printed["exit_code"] == code == 0


def test_the_module_is_runnable_as_a_command(tmp_path: Path) -> None:
    """`python -m automation` is what the Routine prompt names, so it has to actually run."""
    import sys

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    finished = subprocess.run(
        [sys.executable, "-m", "automation", "preflight", "--request", str(_request(tmp_path))],
        capture_output=True,
        text=True,
        cwd=scripts,
    )

    assert finished.returncode == 0, finished.stderr
    assert Status.READY_TO_IMPLEMENT.value in finished.stdout


@pytest.mark.parametrize("status", list(Status))
def test_every_status_is_reachable_as_an_exit_code(status: Status) -> None:
    assert status in EXIT_CODES
