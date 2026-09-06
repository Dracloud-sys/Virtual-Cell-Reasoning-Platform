"""One run, end to end, and the ways the chain between its steps can be broken.

Each step passing on its own says nothing about whether the run is one run. The third review
round was entirely about that gap: a valid token was enough to confirm even after another run
had taken the lock; a refused confirm kept the lock forever; `postflight` accepted a token with
no confirmation behind it; and the path policy came from a request file the agent could widen
after phase one had validated a narrower one.

So these tests break the chain in each of those places and assert the run stops.
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


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


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


def _issue(body: str | None = None) -> dict:
    return {
        "number": 21,
        "title": f"[{WORK_ID}] gate",
        "body": body or SPEC.format(work_id=WORK_ID),
        "state": "OPEN",
        "labels": ["claude-ready"],
    }


def _request(path: Path, lock_dir: Path, *, fresh: bool = False, **extra) -> Path:
    payload: dict = {
        "work_id": WORK_ID,
        "queue_pages": [
            {"issues": [_issue()], "pageInfo": {"hasNextPage": False}, "totalCount": 1}
        ],
        "lock": {"kind": "file", "directory": str(lock_dir)},
    }
    if fresh:
        payload["captured_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _passes(workdir: Path, base: str, unchanged) -> tuple[int, str]:
    return 0, "All checks passed."


class _Chain:
    """The four files a run carries between its steps."""

    def __init__(self, tmp_path: Path) -> None:
        self.locks = tmp_path / "locks"
        self.token = tmp_path / "lock.json"
        self.confirmation = tmp_path / "confirmation.json"
        self.marker = tmp_path / "proceeded.json"
        self.tmp = tmp_path

    def phase1(self, **extra) -> Path:
        return _request(self.tmp / "p1.json", self.locks, **extra)

    def phase2(self, **extra) -> Path:
        return _request(self.tmp / "p2.json", self.locks, fresh=True, **extra)

    def preflight(self, request: Path | None = None) -> int:
        return main(
            ["preflight", "--request", str(request or self.phase1()), "--token", str(self.token)]
        )

    def confirm(self, request: Path | None = None) -> int:
        return main(
            [
                "confirm",
                "--request",
                str(request or self.phase2()),
                "--token",
                str(self.token),
                "--confirmation",
                str(self.confirmation),
                "--proceed-marker",
                str(self.marker),
            ]
        )

    def postflight(self, repo: Path, request: Path | None = None, base: str = "HEAD~1") -> int:
        return main(
            [
                "postflight",
                "--request",
                str(request or self.phase2()),
                "--token",
                str(self.token),
                "--confirmation",
                str(self.confirmation),
                "--base",
                base,
                "--workdir",
                str(repo),
            ]
        )

    def finalize(self, pushed: str, request: Path | None = None) -> int:
        return main(
            [
                "finalize",
                "--request",
                str(request or self.phase1()),
                "--token",
                str(self.token),
                "--confirmation",
                str(self.confirmation),
                "--pushed-sha",
                pushed,
            ]
        )


def _do_work(repo: Path, value: str = "2") -> str:
    (repo / "scripts" / "automation" / "gate.py").write_text(f"x = {value}\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "work", cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


def test_the_whole_chain_runs_and_gives_the_lock_back(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    chain = _Chain(tmp_path)
    monkeypatch.setattr("automation.postflight.run_verify", _passes)

    assert chain.preflight() == 0
    assert chain.token.exists()
    assert not chain.marker.exists()  # taking the lock is not permission to work

    assert chain.confirm() == 0
    assert chain.marker.exists()
    assert chain.confirmation.exists()

    head = _do_work(repo)

    assert chain.postflight(repo) == 0
    assert json.loads(chain.confirmation.read_text())["verified_head"] == head

    # the push happens here; finalize proves the remote carries exactly what was verified
    assert chain.finalize(head) == 0
    assert not chain.token.exists()
    assert chain.preflight() == 0


def test_finalize_refuses_a_commit_that_was_never_verified(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """A push that landed something other than the verified head is not a completed run."""
    chain = _Chain(tmp_path)
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    chain.preflight()
    chain.confirm()
    _do_work(repo)
    chain.postflight(repo)

    assert chain.finalize("0" * 40) == EXIT_CODES[Status.BLOCKED_SCOPE]


def test_a_failed_push_leaves_the_revision_unrecorded(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """postflight passing is not "applied": the fix only exists once the remote has it."""
    chain = _Chain(tmp_path)
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    chain.preflight()
    chain.confirm()
    _do_work(repo)

    assert chain.postflight(repo) == 0
    # the push fails, so finalize is never reached and nothing is recorded
    assert "recorded_revision" not in json.loads(chain.confirmation.read_text()).get("evidence", {})
    assert chain.token.exists()  # and the run can be retried


def test_widening_the_allowed_paths_after_phase_one_does_not_widen_the_diff(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """The bypass: phase one validates a narrow contract, the request file is edited, postflight
    reads the edited one. The policy now comes from a body matching the confirmed hash."""
    chain = _Chain(tmp_path)
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    chain.preflight()
    chain.confirm()

    (repo / "src" / "virtualcell" / "cli.py").write_text("z = 2\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "out of scope", cwd=repo)

    widened = SPEC.format(work_id=WORK_ID).replace(
        "scripts/automation/\ntests/automation/", "scripts/\ntests/\nsrc/"
    )
    tampered = chain.phase2(
        queue_pages=[
            {"issues": [_issue(widened)], "pageInfo": {"hasNextPage": False}, "totalCount": 1}
        ]
    )

    code = chain.postflight(repo, tampered)

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.preflight() == 0  # and the lock came back


def test_an_out_of_scope_change_stops_the_push_and_frees_the_lock(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    chain = _Chain(tmp_path)
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    chain.preflight()
    chain.confirm()

    (repo / "src" / "virtualcell" / "cli.py").write_text("z = 3\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "out of scope", cwd=repo)

    assert chain.postflight(repo) == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.preflight() == 0


def test_postflight_refuses_once_the_lock_has_changed_hands(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    chain = _Chain(tmp_path)
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    chain.preflight()
    chain.confirm()
    _do_work(repo)
    next(chain.locks.iterdir()).write_text("someone-else now nonce\n", encoding="utf-8")

    assert chain.postflight(repo) == EXIT_CODES[Status.ALREADY_RUNNING]


def test_finalize_refuses_once_the_lock_has_changed_hands(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    chain = _Chain(tmp_path)
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    chain.preflight()
    chain.confirm()
    head = _do_work(repo)
    chain.postflight(repo)
    next(chain.locks.iterdir()).write_text("someone-else now nonce\n", encoding="utf-8")

    assert chain.finalize(head) == EXIT_CODES[Status.ALREADY_RUNNING]


def test_a_branch_that_appeared_after_the_lock_stops_the_run(repo: Path, tmp_path: Path) -> None:
    """Another run may be part way through this work; a second branch would fork it."""
    chain = _Chain(tmp_path)
    chain.preflight()

    code = chain.confirm(chain.phase2(existing_branches=[f"claude/{WORK_ID}-someone-else"]))

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]
    assert chain.preflight() == 0  # lock returned


def test_confirming_without_first_locking_is_refused(repo: Path, tmp_path: Path) -> None:
    chain = _Chain(tmp_path)

    assert chain.confirm() == EXIT_CODES[Status.ALREADY_RUNNING]
    assert not chain.marker.exists()


def test_a_restarted_process_can_still_release(repo: Path, tmp_path: Path) -> None:
    """The token is on disk, so the process that releases need not be the one that took it."""
    chain = _Chain(tmp_path)
    chain.preflight()

    finished = subprocess.run(
        [
            "python3",
            str(Path(__file__).resolve().parents[2] / "scripts" / "automation" / "cli.py"),
            "release",
            "--request",
            str(chain.phase1()),
            "--token",
            str(chain.token),
        ],
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stderr
    assert chain.preflight() == 0
