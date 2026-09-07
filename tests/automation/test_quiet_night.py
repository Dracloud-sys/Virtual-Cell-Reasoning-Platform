"""The night nothing is approved, driven through the CLI with the file a run could actually write.

This is the case the whole package was built to keep distinct from a malfunction, and it was the
one case no test drove end to end. The existing empty-queue tests all went through a helper that
had already filled in a `work_id` and a valid `target.branch` — values a real quiet run has
nowhere to get, because both come from an issue that does not exist. So `preflight` reached
`_target_shape` first and answered `INVALID_SPEC` (12): "you wrote a bad request", standing in
for "there was nothing to do".

Everything here therefore starts from the raw captured `list_issues` response and a request
carrying **nothing else** — no work id, no target, no branch snapshot. The gate's answer must be
`NO_READY_WORK` (10), and it must arrive having touched nothing at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from automation.outcomes import EXIT_CODES, Status
from automation.runner import main
from workspace import Workspace

FIXTURES = Path(__file__).parent / "fixtures" / "github"


def _captured(name: str) -> dict:
    """A response as the GitHub tool actually returned it, not one written to pass."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _minimal(tmp_path: Path, *pages: dict, workdir: str = ".") -> Path:
    """All a run can honestly say when the queue came back empty."""
    path = tmp_path / "phase1.json"
    path.write_text(
        json.dumps({"queue_pages": list(pages), "queue_error": None, "workdir": workdir}),
        encoding="utf-8",
    )
    return path


def _preflight(request: Path, tmp_path: Path) -> int:
    """Production mode — no `--development`, so this is the path the Routine takes."""
    return main(["preflight", "--request", str(request), "--token", str(tmp_path / "lock.json")])


# --- the quiet night ---------------------------------------------------------------------------


def test_an_empty_queue_ends_the_run_at_exit_ten(tmp_path: Path, capsys) -> None:
    code = _preflight(_minimal(tmp_path, _captured("list_issues_empty.json")), tmp_path)

    assert code == EXIT_CODES[Status.NO_READY_WORK]
    assert "NO_READY_WORK" in capsys.readouterr().out


def test_the_quiet_night_needs_no_work_id_and_no_branch(tmp_path: Path, capsys) -> None:
    """The regression, named for what it is: neither exists to be stated, so neither is asked."""
    code = _preflight(_minimal(tmp_path, _captured("list_issues_empty.json")), tmp_path)

    printed = capsys.readouterr().out
    assert code == EXIT_CODES[Status.NO_READY_WORK]
    assert "INVALID_SPEC" not in printed
    assert "target.branch" not in printed


def test_nothing_is_written_when_there_is_nothing_to_do(tmp_path: Path) -> None:
    _preflight(_minimal(tmp_path, _captured("list_issues_empty.json")), tmp_path)

    assert not (tmp_path / "lock.json").exists()
    assert not (tmp_path / "proceeded.json").exists()
    assert not (tmp_path / "confirmation.json").exists()
    assert list(tmp_path.iterdir()) == [tmp_path / "phase1.json"]


def test_the_quiet_night_runs_no_git_at_all(tmp_path: Path, monkeypatch) -> None:
    """One trap covers every question the old order asked before reading the queue.

    `git remote get-url` for the checkout identity, `git ls-remote` for the base branch and for
    the lock ref, the fetch behind the applied-revisions store: all of them are `subprocess.run`,
    and every module in the package reaches it through the shared `subprocess` module object.
    So a single patch proves the negative rather than four separate assertions guessing at it.
    """

    def refuse(*args, **kwargs):
        raise AssertionError(f"the quiet night consulted git: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)

    assert (
        _preflight(_minimal(tmp_path, _captured("list_issues_empty.json")), tmp_path)
        == EXIT_CODES[Status.NO_READY_WORK]
    )


def test_no_ref_appears_on_a_real_remote(tmp_path: Path, workspace: Workspace) -> None:
    """The same claim asked of a real bare repository rather than of a patched function."""
    before = workspace.git("ls-remote", str(workspace.remote))

    code = _preflight(
        _minimal(tmp_path, _captured("list_issues_empty.json"), workdir=str(workspace.root)),
        tmp_path,
    )

    assert code == EXIT_CODES[Status.NO_READY_WORK]
    assert workspace.git("ls-remote", str(workspace.remote)) == before


def test_a_checkout_that_is_not_production_still_reports_the_quiet_night(
    tmp_path: Path, workspace: Workspace, capsys
) -> None:
    """The queue is asked first, so its answer is not withheld pending a question about scope.

    This workspace is not the configured repository, which `_target_shape` refuses. That refusal
    is right when there is work to do and beside the point when there is none.
    """
    workspace.git("remote", "add", "origin", "https://github.com/someone/else.git")

    code = _preflight(
        _minimal(tmp_path, _captured("list_issues_empty.json"), workdir=str(workspace.root)),
        tmp_path,
    )

    assert code == EXIT_CODES[Status.NO_READY_WORK]
    assert "someone/else" not in capsys.readouterr().out


# --- the two answers an empty-looking queue must not be allowed to become ----------------------


@pytest.mark.parametrize("fixture", ["rest_error_401.json", "graphql_errors.json"])
def test_a_failed_query_is_not_a_quiet_night(tmp_path: Path, fixture: str) -> None:
    code = _preflight(_minimal(tmp_path, _captured(fixture)), tmp_path)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert not (tmp_path / "lock.json").exists()


def test_an_incomplete_read_is_not_a_quiet_night(tmp_path: Path, capsys) -> None:
    """`totalCount` says two matched and none arrived. That is a broken read, not an empty one."""
    page = _captured("list_issues_empty.json") | {"totalCount": 2}

    code = _preflight(_minimal(tmp_path, page), tmp_path)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert "incomplete read" in capsys.readouterr().out


def test_a_queue_error_is_not_a_quiet_night(tmp_path: Path) -> None:
    """The field exists so a caught exception never arrives shaped like an empty page list."""
    path = tmp_path / "phase1.json"
    path.write_text(
        json.dumps({"queue_pages": [], "queue_error": "connection reset", "workdir": "."}),
        encoding="utf-8",
    )

    assert _preflight(path, tmp_path) == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]


def test_two_approved_issues_are_refused_before_anything_else_is_asked(tmp_path: Path) -> None:
    """`AMBIGUOUS_QUEUE` is also the queue's own answer, and also owes nothing to the target."""
    one = _captured("list_issues_one.json")
    second = dict(one["issues"][0]) | {"number": 20, "title": "[vcrp-ops-002] other"}
    page = one | {"issues": [one["issues"][0], second], "totalCount": 2}

    code = _preflight(_minimal(tmp_path, page), tmp_path)

    assert code == EXIT_CODES[Status.AMBIGUOUS_QUEUE]
    assert not (tmp_path / "lock.json").exists()


def test_one_approved_issue_still_has_to_answer_for_its_target(tmp_path: Path, capsys) -> None:
    """The gate below the queue is unchanged: exactly one issue, and the target is asked for."""
    code = _preflight(_minimal(tmp_path, _captured("list_issues_one.json")), tmp_path)

    assert code == EXIT_CODES[Status.INVALID_SPEC]
    assert "target.branch" in capsys.readouterr().out
