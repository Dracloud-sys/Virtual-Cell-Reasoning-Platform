"""The commands a scheduled run actually invokes, driven the way it invokes them.

The first review round found that the checks were unreachable from any real caller. The second
found that the command documented for reaching them did not run from the repository root, and
that "re-read after locking" was two snapshots taken before the lock. Both are regression cases
here, because both were things that passed their own tests while being false.

Every test asserts the **exit code** — that is what a shell branches on — and, wherever the run
should stop, the **absence of the proceed marker**, which is the observable stand-in for "and
then it did not go on to do any work". Only `confirm` ever writes that marker: taking the lock
is not permission to work.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from automation.outcomes import EXIT_CODES, Status
from automation.runner import main
from workspace import Workspace

WORK_ID = "vcrp-ops-002"
BRANCH = f"claude/{WORK_ID}-gate"
HEAD = "1b716d75d6c0c60eac8930018d75ee184ad36a47"
REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = (Path(__file__).parent / "fixtures" / "complete_spec.md").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _bind(shared_workspace: Workspace, monkeypatch) -> None:
    """Every request in this file points at one real remote, so phase one can resolve its base.

    Module-scoped on purpose: these tests read `main` off the remote and never write to it, and
    a clone per test would pay for a fixture nothing here modifies.
    """
    monkeypatch.setattr(_Target, "workspace", shared_workspace, raising=False)


class _Target:
    """Where the shared workspace is parked, so the request builders can reach it."""

    workspace: Workspace


def _target() -> dict:
    ws = _Target.workspace
    return {"remote": str(ws.remote), "branch": BRANCH, "base_branch": "main"}


def _issue(number: int = 21, work_id: str = WORK_ID, body: str | None = None) -> dict:
    return {
        "number": number,
        "title": f"[{work_id}] gate",
        "body": _TEMPLATE.format(work_id=work_id) if body is None else body,
        "state": "OPEN",
        "labels": ["claude-ready"],
    }


def _page(issues: list[dict], *, has_next: bool = False) -> dict:
    return {"issues": issues, "pageInfo": {"hasNextPage": has_next}, "totalCount": len(issues)}


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _phase1(tmp_path: Path, **overrides) -> Path:
    payload = {
        "work_id": WORK_ID,
        "workdir": str(_Target.workspace.root),
        "target": _target(),
        "queue_pages": [_page([_issue()])],
        "lock": {"kind": "file", "directory": str(tmp_path / "locks")},
    }
    payload.update(overrides)
    return _write(tmp_path / "phase1.json", payload)


def _phase2(tmp_path: Path, *, captured_at: str | None = None, **overrides) -> Path:
    payload = {
        "work_id": WORK_ID,
        "workdir": str(_Target.workspace.root),
        "target": _target(),
        "captured_at": captured_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "queue_pages": [_page([_issue()])],
        "lock": {"kind": "file", "directory": str(tmp_path / "locks")},
    }
    payload.update(overrides)
    return _write(tmp_path / "phase2.json", payload)


def _run(command: str, *args: str) -> int:
    """`--development` on every call: a file lock is refused without it, which is the point."""
    return main([command, *args, "--development"])


def _preflight(tmp_path: Path, request: Path | None = None) -> tuple[int, Path]:
    token = tmp_path / "lock.json"
    code = _run("preflight", "--request", str(request or _phase1(tmp_path)), "--token", str(token))
    return code, token


def _confirm(tmp_path: Path, token: Path, request: Path | None = None) -> tuple[int, Path]:
    marker = tmp_path / "proceeded.json"
    code = _run(
        "confirm",
        "--request",
        str(request or _phase2(tmp_path)),
        "--token",
        str(token),
        "--confirmation",
        str(tmp_path / "confirmation.json"),
        "--proceed-marker",
        str(marker),
    )
    return code, marker


# --- regression: the canonical command must run from the repository root ---------------------


def test_the_canonical_command_runs_from_the_repository_root(tmp_path: Path) -> None:
    """`python -m automation` needed scripts/ on PYTHONPATH and failed exactly where it is used.

    The old integration test passed by running with cwd=scripts — arranging the one condition
    the real caller cannot provide.
    """
    finished = subprocess.run(
        [
            sys.executable,
            "scripts/automation/cli.py",
            "preflight",
            "--request",
            str(_phase1(tmp_path)),
            "--token",
            str(tmp_path / "lock.json"),
            "--development",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stderr
    assert "No module named" not in finished.stderr


def test_the_old_module_invocation_is_not_what_the_docs_promise(tmp_path: Path) -> None:
    """Pinning the reason the command changed, so nobody restores the broken one."""
    finished = subprocess.run(
        [sys.executable, "-m", "automation", "preflight", "--request", "x", "--token", "y"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert finished.returncode != 0
    assert "No module named automation" in finished.stderr


# --- phase one: taking the lock is not permission to work ------------------------------------


def test_preflight_takes_the_lock_and_stops(tmp_path: Path) -> None:
    code, token = _preflight(tmp_path)

    assert code == 0
    assert token.exists()
    assert not (tmp_path / "proceeded.json").exists()
    assert json.loads(token.read_text())["work_id"] == WORK_ID


def test_an_empty_queue_refuses_and_writes_no_token(tmp_path: Path) -> None:
    code, token = _preflight(tmp_path, _phase1(tmp_path, queue_pages=[_page([])]))

    assert code == EXIT_CODES[Status.NO_READY_WORK]
    assert not token.exists()


def test_a_failed_query_refuses_with_its_own_code(tmp_path: Path) -> None:
    request = _phase1(tmp_path, queue_pages=[], queue_error="403 Forbidden")

    code, token = _preflight(tmp_path, request)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert code != EXIT_CODES[Status.NO_READY_WORK]
    assert not token.exists()


def test_a_bad_credentials_envelope_is_not_an_empty_queue(tmp_path: Path) -> None:
    """Regression: {"message": "Bad credentials", "status": "401"} read as a healthy empty queue."""
    request = _phase1(tmp_path, queue_pages=[{"message": "Bad credentials", "status": "401"}])

    code, token = _preflight(tmp_path, request)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert not token.exists()


def test_a_truncated_page_refuses_rather_than_dispatching_one_issue(tmp_path: Path) -> None:
    request = _phase1(tmp_path, queue_pages=[_page([_issue()], has_next=True)])

    code, _ = _preflight(tmp_path, request)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]


def test_two_approved_issues_refuse(tmp_path: Path) -> None:
    request = _phase1(tmp_path, queue_pages=[_page([_issue(21), _issue(22)])])

    code, _ = _preflight(tmp_path, request)

    assert code == EXIT_CODES[Status.AMBIGUOUS_QUEUE]


def test_an_unfinished_spec_refuses(tmp_path: Path) -> None:
    request = _phase1(tmp_path, queue_pages=[_page([_issue(body="## Goal\n\nTODO\n")])])

    code, _ = _preflight(tmp_path, request)

    assert code == EXIT_CODES[Status.INVALID_SPEC]


def test_a_work_id_the_issue_does_not_declare_refuses(tmp_path: Path) -> None:
    code, _ = _preflight(tmp_path, _phase1(tmp_path, work_id="vcrp-ops-999"))

    assert code == EXIT_CODES[Status.WORK_ID_MISMATCH]


def test_an_open_pull_request_refuses_and_opens_no_second_one(tmp_path: Path) -> None:
    request = _phase1(
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

    code, token = _preflight(tmp_path, request)

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]
    assert not token.exists()


def test_a_second_run_while_the_first_holds_the_lock_refuses(tmp_path: Path) -> None:
    first, _ = _preflight(tmp_path)
    second = _run(
        "preflight", "--request", str(_phase1(tmp_path)), "--token", str(tmp_path / "other.json")
    )

    assert first == 0
    assert second == EXIT_CODES[Status.ALREADY_RUNNING]


# --- phase two: the real re-read --------------------------------------------------------------


def test_confirm_grants_permission_after_a_fresh_re_read(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)

    code, marker = _confirm(tmp_path, token)

    assert code == 0
    assert marker.exists()
    assert json.loads(marker.read_text())["evidence"]["phase"] == "2 of 2"


def test_evidence_gathered_before_the_lock_is_refused(tmp_path: Path, capsys) -> None:
    """Regression: the first version read both snapshots out of one pre-lock request file."""
    _, token = _preflight(tmp_path)
    capsys.readouterr()
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat(timespec="seconds")

    code, marker = _confirm(tmp_path, token, _phase2(tmp_path, captured_at=stale))

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert "stale snapshot, not a re-read" in capsys.readouterr().out
    assert not marker.exists()


def test_a_confirmation_without_a_timestamp_is_refused(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)
    request = _phase2(tmp_path)
    payload = json.loads(request.read_text())
    payload.pop("captured_at")
    _write(request, payload)

    code, marker = _confirm(tmp_path, token, request)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert not marker.exists()


def test_confirm_without_a_token_refuses(tmp_path: Path) -> None:
    code, marker = _confirm(tmp_path, tmp_path / "absent.json")

    assert code == EXIT_CODES[Status.ALREADY_RUNNING]
    assert not marker.exists()


def test_a_label_pulled_between_the_phases_is_caught(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)

    code, marker = _confirm(tmp_path, token, _phase2(tmp_path, queue_pages=[_page([])]))

    assert code == EXIT_CODES[Status.NO_READY_WORK]
    assert not marker.exists()


def test_a_pull_request_opened_between_the_phases_is_caught(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)
    late = _phase2(
        tmp_path,
        pull_requests=[
            {
                "number": 99,
                "state": "open",
                "title": "t",
                "head": {"ref": f"claude/{WORK_ID}-gate", "sha": HEAD},
            }
        ],
    )

    code, marker = _confirm(tmp_path, token, late)

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]
    assert not marker.exists()


def test_the_issue_body_changing_between_the_phases_is_caught(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)
    edited = _issue()
    edited["body"] += "\n\n## Extra\n\nsomeone edited the contract mid-run.\n"

    code, marker = _confirm(tmp_path, token, _phase2(tmp_path, queue_pages=[_page([edited])]))

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]
    assert not marker.exists()


def test_a_confirmation_for_a_different_work_id_is_refused(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)

    code, marker = _confirm(tmp_path, token, _phase2(tmp_path, work_id="vcrp-ops-777"))

    assert code == EXIT_CODES[Status.WORK_ID_MISMATCH]
    assert not marker.exists()


# --- release ----------------------------------------------------------------------------------


def test_release_lets_the_next_run_start(tmp_path: Path) -> None:
    """Regression: the lock lived in a process attribute, so the first run stranded it."""
    _, token = _preflight(tmp_path)

    released = _run("release", "--request", str(_phase1(tmp_path)), "--token", str(token))
    again, _ = _preflight(tmp_path)

    assert released == 0
    assert again == 0


def test_release_without_a_token_is_refused(tmp_path: Path) -> None:
    code = _run(
        "release", "--request", str(_phase1(tmp_path)), "--token", str(tmp_path / "none.json")
    )

    assert code == EXIT_CODES[Status.ALREADY_RUNNING]


def test_an_unreadable_request_is_a_blocked_access_not_a_crash(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    code = _run("preflight", "--request", str(broken), "--token", str(tmp_path / "lock.json"))

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]


# --- regressions from the third review round --------------------------------------------------


def test_a_request_may_not_name_its_own_approvers(tmp_path: Path) -> None:
    """The agent writes the request, so an approver list it can point at is one it can write."""
    request = _phase1(tmp_path, approvers_file=str(tmp_path / "mine.json"))

    code, token = _preflight(tmp_path, request)

    assert code == EXIT_CODES[Status.INVALID_SPEC]
    assert not token.exists()


def test_an_inline_approver_list_is_refused_too(tmp_path: Path) -> None:
    code, _ = _preflight(tmp_path, _phase1(tmp_path, approvers=["me"]))

    assert code == EXIT_CODES[Status.INVALID_SPEC]


def test_confirm_refuses_when_the_lock_was_taken_by_someone_else(tmp_path: Path) -> None:
    """A token proves what this run took. It says nothing about who holds the lock now."""
    _, token = _preflight(tmp_path)
    lock = next((tmp_path / "locks").iterdir())
    lock.write_text("another-run 2026-09-06T00:00:00+00:00 deadbeef\n", encoding="utf-8")

    code, marker = _confirm(tmp_path, token)

    assert code == EXIT_CODES[Status.ALREADY_RUNNING]
    assert not marker.exists()


def test_confirm_refuses_when_the_lock_is_gone(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)
    next((tmp_path / "locks").iterdir()).unlink()

    code, marker = _confirm(tmp_path, token)

    assert code == EXIT_CODES[Status.ALREADY_RUNNING]
    assert not marker.exists()


def test_a_refused_confirm_frees_the_lock_for_the_next_run(tmp_path: Path) -> None:
    """Otherwise a withdrawn label leaves every later run reporting ALREADY_RUNNING."""
    first, token = _preflight(tmp_path)
    assert first == 0

    refused, _ = _confirm(tmp_path, token, _phase2(tmp_path, queue_pages=[_page([])]))
    again, _ = _preflight(tmp_path)

    assert refused == EXIT_CODES[Status.NO_READY_WORK]
    assert again == 0


def test_a_refused_confirm_clears_the_token(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)

    _confirm(tmp_path, token, _phase2(tmp_path, queue_pages=[_page([])]))

    assert not token.exists()


def test_postflight_without_a_confirmation_is_refused(tmp_path: Path) -> None:
    """preflight -> postflight would skip the re-read entirely."""
    _, token = _preflight(tmp_path)

    code = _run(
        "postflight",
        "--request",
        str(_phase1(tmp_path)),
        "--token",
        str(token),
        "--confirmation",
        str(tmp_path / "never-confirmed.json"),
    )

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]


def test_a_confirmation_from_another_run_is_refused(tmp_path: Path) -> None:
    _, token = _preflight(tmp_path)
    _confirm(tmp_path, token)
    stolen = json.loads((tmp_path / "confirmation.json").read_text())
    stolen["token_identity"] = "0" * 64
    (tmp_path / "confirmation.json").write_text(json.dumps(stolen), encoding="utf-8")

    code = _run(
        "postflight",
        "--request",
        str(_phase1(tmp_path)),
        "--token",
        str(token),
        "--confirmation",
        str(tmp_path / "confirmation.json"),
    )

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]


def test_a_phase_two_file_written_before_the_lock_is_refused(tmp_path: Path) -> None:
    """`captured_at` is a string the agent writes; the file's own age is the weaker check."""
    early = _phase2(tmp_path)
    _, token = _preflight(tmp_path)
    # keep the asserted timestamp fresh, but the file itself predates the lock
    payload = json.loads(early.read_text())
    payload["captured_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    early.write_text(json.dumps(payload), encoding="utf-8")
    import os

    stale = json.loads(token.read_text())["acquired_at"]
    when = datetime.fromisoformat(stale).timestamp() - 60
    os.utime(early, (when, when))

    code, marker = _confirm(tmp_path, token, early)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert not marker.exists()
