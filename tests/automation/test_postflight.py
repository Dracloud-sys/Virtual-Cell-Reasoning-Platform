"""The gate between "the work is done" and "the work is pushed", driven on real diffs.

`PathPolicy` had tests and no caller. `BLOCKED_SCOPE` was a status the entry point could not
reach, so a run could finish by pushing anything at all as long as it had started legally. These
tests go through `run_postflight` with a real git repository, real renames, and a real exit code
from the verification step.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from automation.outcomes import Status
from automation.postflight import PostflightInputs, changed_paths, run_postflight

SPEC = (Path(__file__).parent / "fixtures" / "complete_spec.md").read_text(encoding="utf-8")
BODY = SPEC.format(work_id="vcrp-ops-002")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    (work / "scripts" / "automation").mkdir(parents=True)
    (work / "src" / "virtualcell" / "reasoning" / "kernel").mkdir(parents=True)
    _git("init", "--quiet", "-b", "main", cwd=work)
    _git("config", "user.email", "t@t.invalid", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    (work / "scripts" / "automation" / "gate.py").write_text("x = 1\n")
    (work / "src" / "virtualcell" / "reasoning" / "kernel" / "decide.py").write_text("y = 1\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-qm", "base", cwd=work)
    return work


def _passes(workdir: Path, base: str, unchanged) -> tuple[int, str]:
    return 0, "All checks passed."


def _fails(workdir: Path, base: str, unchanged) -> tuple[int, str]:
    return 1, "FAILED: pytest (full)"


def _skipped(workdir: Path, base: str, unchanged) -> tuple[int, str]:
    return 2, "9 checks passed, 1 NOT RUN: kernel unchanged."


def _inputs(repo: Path, **overrides) -> PostflightInputs:
    base = dict(
        work_id="vcrp-ops-002",
        issue_body=BODY,
        base="HEAD~1",
        workdir=repo,
        verify=_passes,
    )
    base.update(overrides)
    return PostflightInputs(**base)  # type: ignore[arg-type]


def _commit(repo: Path, message: str = "work") -> None:
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", message, cwd=repo)


def test_a_change_inside_the_allowed_paths_is_cleared_to_push(repo: Path) -> None:
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 2\n")
    _commit(repo)

    outcome = run_postflight(_inputs(repo))

    assert outcome.status is Status.READY_TO_IMPLEMENT
    assert outcome.evidence["verify_exit"] == "0"


def test_a_change_outside_the_allowed_paths_is_blocked(repo: Path) -> None:
    """The status the entry point could not previously reach, reached from a real diff."""
    (repo / "pyproject.toml").write_text("[project]\n")
    _commit(repo)

    outcome = run_postflight(_inputs(repo))

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "pyproject.toml" in outcome.detail


def test_an_unauthorised_kernel_change_is_blocked(repo: Path) -> None:
    (repo / "src" / "virtualcell" / "reasoning" / "kernel" / "decide.py").write_text("y = 2\n")
    _commit(repo)

    outcome = run_postflight(_inputs(repo))

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "kernel" in outcome.detail


def test_a_rename_out_of_the_kernel_is_seen_at_both_ends(repo: Path) -> None:
    """Judging only where the file landed would call this an ordinary scripts/ change."""
    source = repo / "src" / "virtualcell" / "reasoning" / "kernel" / "decide.py"
    target = repo / "scripts" / "automation" / "decide.py"
    _git("mv", str(source.relative_to(repo)), str(target.relative_to(repo)), cwd=repo)
    _commit(repo, "move it out")

    changes = changed_paths("HEAD~1", workdir=repo)
    outcome = run_postflight(_inputs(repo))

    assert any(change.previous_path for change in changes)
    assert outcome.status is Status.BLOCKED_SCOPE
    assert "kernel" in outcome.detail


def test_a_failed_verification_blocks_the_push(repo: Path) -> None:
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 3\n")
    _commit(repo)

    outcome = run_postflight(_inputs(repo, verify=_fails))

    assert not outcome.proceeds
    assert "exit 1" in outcome.detail


def test_a_partial_verification_blocks_the_push(repo: Path) -> None:
    """Exit 2 means something was skipped, and a skipped check is not a passed one."""
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 4\n")
    _commit(repo)

    outcome = run_postflight(_inputs(repo, verify=_skipped))

    assert not outcome.proceeds
    assert "exit 2" in outcome.detail


def test_an_applied_revision_is_recorded_before_the_push_is_allowed(repo: Path) -> None:
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 5\n")
    _commit(repo)
    recorded: list[str] = []

    class Recorder:
        def record(self, identifier: str) -> None:
            recorded.append(identifier)

    outcome = run_postflight(_inputs(repo, revision_id="review-771", recorder=Recorder()))

    assert outcome.proceeds
    assert recorded == ["review-771"]
    assert outcome.evidence["recorded_revision"] == "review-771"


def test_an_applied_revision_with_nowhere_to_record_it_blocks(repo: Path) -> None:
    """Otherwise the next run reads "not applied" and does the same work again."""
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 6\n")
    _commit(repo)

    outcome = run_postflight(_inputs(repo, revision_id="review-771", recorder=None))

    assert outcome.status is Status.BLOCKED_GITHUB_ACCESS
    assert "record" in outcome.detail


def test_a_recorder_that_fails_blocks_the_push(repo: Path) -> None:
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 7\n")
    _commit(repo)

    class Broken:
        def record(self, identifier: str) -> None:
            raise RuntimeError("remote unreachable")

    outcome = run_postflight(_inputs(repo, revision_id="review-771", recorder=Broken()))

    assert not outcome.proceeds
    assert "remote unreachable" in outcome.detail


def test_an_issue_that_stopped_validating_mid_run_blocks(repo: Path) -> None:
    (repo / "scripts" / "automation" / "gate.py").write_text("x = 8\n")
    _commit(repo)

    outcome = run_postflight(_inputs(repo, issue_body="## Goal\n\nTODO\n"))

    assert outcome.status is Status.INVALID_SPEC


def test_an_unresolvable_base_is_reported_rather_than_assumed_clean(repo: Path) -> None:
    outcome = run_postflight(_inputs(repo, base="refs/heads/does-not-exist"))

    assert not outcome.proceeds


def test_no_changes_at_all_is_not_a_scope_violation(repo: Path) -> None:
    _git("commit", "-q", "--allow-empty", "-m", "nothing", cwd=repo)

    outcome = run_postflight(_inputs(repo))

    assert outcome.proceeds
    assert outcome.evidence["changed_paths"] == "0"
