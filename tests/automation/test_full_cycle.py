"""One run, end to end, through the commands in the order a scheduled run issues them.

Every other test in this directory checks one decision. This one checks that the decisions
compose: that the lock taken in phase one is the lock phase two presents, that permission is
granted only after a re-read, that the work is judged against a real diff before anything is
pushed, and that the lock comes back afterwards so the next night is not blocked by this one.

The failures it pins are the ones that survived the previous rounds precisely because each
piece passed on its own:

* preflight granted permission by itself, so the "re-read" never happened;
* the lock lived in a process attribute, so the first successful run stranded it;
* nothing ever called the scope check, so `BLOCKED_SCOPE` was unreachable from the CLI.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from automation.outcomes import EXIT_CODES, Status
from automation.runner import main

WORK_ID = "vcrp-ops-002"
SPEC = (Path(__file__).parent / "fixtures" / "complete_spec.md").read_text(encoding="utf-8")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    (work / "scripts" / "automation").mkdir(parents=True)
    (work / "src" / "virtualcell").mkdir(parents=True)
    _git("init", "--quiet", "-b", "main", cwd=work)
    _git("config", "user.email", "t@t.invalid", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    (work / "scripts" / "automation" / "gate.py").write_text("x = 1\n")
    (work / "src" / "virtualcell" / "cli.py").write_text("z = 1\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-qm", "base", cwd=work)
    return work


def _issue() -> dict:
    return {
        "number": 21,
        "title": f"[{WORK_ID}] gate",
        "body": SPEC.format(work_id=WORK_ID),
        "state": "OPEN",
        "labels": ["claude-ready"],
    }


def _request(path: Path, lock_dir: Path, *, captured_at: str | None = None, **extra) -> Path:
    payload = {
        "work_id": WORK_ID,
        "queue_pages": [
            {"issues": [_issue()], "pageInfo": {"hasNextPage": False}, "totalCount": 1}
        ],
        "lock": {"kind": "file", "directory": str(lock_dir)},
    }
    if captured_at:
        payload["captured_at"] = captured_at
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _passes(workdir: Path, base: str, unchanged) -> tuple[int, str]:
    return 0, "All checks passed."


def test_the_whole_cycle_runs_and_gives_the_lock_back(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    lock_dir = tmp_path / "locks"
    token = tmp_path / "lock.json"
    marker = tmp_path / "proceeded.json"
    phase1 = _request(tmp_path / "p1.json", lock_dir)

    # phase 1 - take the lock. This is not permission to work.
    assert main(["preflight", "--request", str(phase1), "--token", str(token)]) == 0
    assert token.exists()
    assert not marker.exists()

    # the agent now re-queries GitHub. That happens between processes, which is the point.
    phase2 = _request(
        tmp_path / "p2.json",
        lock_dir,
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    # phase 2 - permission, granted only against evidence gathered after the lock.
    assert (
        main(
            [
                "confirm",
                "--request",
                str(phase2),
                "--token",
                str(token),
                "--proceed-marker",
                str(marker),
            ]
        )
        == 0
    )
    assert marker.exists()

    # the implementation happens here, inside the allowed paths.
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 2\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "work", cwd=repo)

    # postflight - the finished diff is judged before anything is pushed.
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    assert (
        main(
            [
                "postflight",
                "--request",
                str(phase1),
                "--token",
                str(token),
                "--base",
                "HEAD~1",
                "--workdir",
                str(repo),
            ]
        )
        == 0
    )

    # release - and the next run can start.
    assert main(["release", "--request", str(phase1), "--token", str(token)]) == 0
    assert main(["preflight", "--request", str(phase1), "--token", str(token)]) == 0


def test_a_scope_violation_stops_the_push_and_frees_the_lock(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """BLOCKED_SCOPE, reached from the CLI against a real diff, for the first time."""
    lock_dir = tmp_path / "locks"
    token = tmp_path / "lock.json"
    phase1 = _request(tmp_path / "p1.json", lock_dir)
    main(["preflight", "--request", str(phase1), "--token", str(token)])

    (repo / "src" / "virtualcell" / "cli.py").write_text("z = 2\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "out of scope", cwd=repo)

    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    code = main(
        [
            "postflight",
            "--request",
            str(phase1),
            "--token",
            str(token),
            "--base",
            "HEAD~1",
            "--workdir",
            str(repo),
        ]
    )

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    # the failed run must not hold the lock hostage
    assert main(["preflight", "--request", str(phase1), "--token", str(token)]) == 0


def test_confirming_without_first_locking_is_refused(repo: Path, tmp_path: Path) -> None:
    phase2 = _request(
        tmp_path / "p2.json",
        tmp_path / "locks",
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    code = main(
        [
            "confirm",
            "--request",
            str(phase2),
            "--token",
            str(tmp_path / "never-written.json"),
            "--proceed-marker",
            str(tmp_path / "proceeded.json"),
        ]
    )

    assert code == EXIT_CODES[Status.ALREADY_RUNNING]
    assert not (tmp_path / "proceeded.json").exists()


def test_a_restarted_process_can_still_release(repo: Path, tmp_path: Path) -> None:
    """The token is on disk, so the process that releases need not be the one that took it."""
    lock_dir = tmp_path / "locks"
    token = tmp_path / "lock.json"
    phase1 = _request(tmp_path / "p1.json", lock_dir)
    main(["preflight", "--request", str(phase1), "--token", str(token)])

    # a fresh interpreter, standing in for the container coming back after a restart
    finished = subprocess.run(
        [
            "python3",
            str(Path(__file__).resolve().parents[2] / "scripts" / "automation" / "cli.py"),
            "release",
            "--request",
            str(phase1),
            "--token",
            str(token),
        ],
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stderr
    assert main(["preflight", "--request", str(phase1), "--token", str(token)]) == 0
