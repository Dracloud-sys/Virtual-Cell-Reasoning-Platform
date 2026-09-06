"""Which repository a run acts on, and why the request does not get to say.

The fourth round moved the base and the pushed commit off the caller's word and onto the
remote's. The fifth round's finding was that the caller still chose *the remote*: `target.remote`,
`target.base_branch`, `lock.remote` and `state.remote` all came out of the request file, so
pointing phase one at another reachable repository bound that as production and every later check
verified the wrong thing carefully.

These tests are all refusals that happen **before the lock**, which is also why they are safe to
run against the real committed configuration: nothing here reaches a push.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from automation.outcomes import EXIT_CODES, Status
from automation.production import (
    CONFIG_PATH,
    TargetConfigError,
    checkout_problem,
    load_target,
    normalise_repository,
)
from automation.runner import main
from workspace import Workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "vcrp-ops-002"
BRANCH = f"claude/{WORK_ID}-gate"
SPEC = (Path(__file__).parent / "fixtures" / "complete_spec.md").read_text(encoding="utf-8")


@pytest.fixture
def config():
    return load_target(REPO_ROOT / CONFIG_PATH)


def _request(tmp_path: Path, workspace: Workspace, **blocks) -> Path:
    payload: dict = {
        "work_id": WORK_ID,
        "workdir": str(workspace.root),
        "target": {"branch": BRANCH},
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "queue_pages": [
            {
                "issues": [
                    {
                        "number": 21,
                        "title": f"[{WORK_ID}] gate",
                        "body": SPEC.format(work_id=WORK_ID),
                        "state": "OPEN",
                        "labels": ["claude-ready"],
                    }
                ],
                "pageInfo": {"hasNextPage": False},
                "totalCount": 1,
            }
        ],
    }
    for block, fields in blocks.items():
        payload[block] = {**payload.get(block, {}), **fields}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _preflight(request: Path, tmp_path: Path) -> int:
    """Production mode: no --development, so the committed configuration is the authority."""
    return main(["preflight", "--request", str(request), "--token", str(tmp_path / "lock.json")])


# --- the committed configuration ---------------------------------------------------------------


def test_the_repositorys_own_target_config_loads(config) -> None:
    assert config.repository == "Dracloud-sys/Virtual-Cell-Reasoning-Platform"
    assert config.remote == "origin"
    assert config.base_branch == "main"
    assert config.branch_prefix == "claude/"
    assert config.lock_namespace.startswith("refs/")
    assert config.state_ref.startswith("refs/")


def test_a_missing_config_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(TargetConfigError):
        load_target(tmp_path / "absent.json")


def test_a_config_missing_a_field_is_refused_rather_than_defaulted(tmp_path: Path) -> None:
    path = tmp_path / "run_target.json"
    path.write_text(json.dumps({"repository": "o/r", "remote": "origin"}), encoding="utf-8")

    with pytest.raises(TargetConfigError) as raised:
        load_target(path)

    assert "base_branch" in str(raised.value)


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:Dracloud-sys/Virtual-Cell-Reasoning-Platform.git",
        "https://github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform",
        "https://github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform.git",
        "https://x-access-token:ghs_secret@github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform",
        "ssh://git@github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform.git",
    ],
)
def test_every_shape_github_hands_out_normalises_to_one_repository(url: str) -> None:
    assert normalise_repository(url) == "dracloud-sys/virtual-cell-reasoning-platform"


@pytest.mark.parametrize(
    "url", ["https://gitlab.com/o/r.git", "/tmp/somewhere/origin.git", "github.com.evil.test/o/r"]
)
def test_anything_that_is_not_a_github_url_is_refused(url: str) -> None:
    with pytest.raises(TargetConfigError):
        normalise_repository(url)


def test_a_checkout_of_something_else_is_named_as_the_problem(config, workspace: Workspace) -> None:
    workspace.git("remote", "add", "origin", str(workspace.remote))

    problem = checkout_problem(config, workdir=workspace.root)

    assert problem is not None
    assert "not a GitHub repository URL" in problem


# --- what a request may not choose ------------------------------------------------------------


@pytest.mark.parametrize(
    ("block", "fields"),
    [
        ("target", {"remote": "elsewhere"}),
        ("target", {"base_branch": "release"}),
        ("target", {"repository": "someone/else"}),
        ("lock", {"kind": "file", "directory": "/tmp/locks"}),
        ("lock", {"remote": "elsewhere"}),
        ("lock", {"namespace": "refs/mine"}),
        ("state", {"kind": "memory"}),
        ("state", {"remote": "elsewhere"}),
        ("state", {"ref": "refs/mine/applied"}),
    ],
)
def test_a_request_may_not_choose_the_production_target(
    tmp_path: Path, workspace: Workspace, block: str, fields: dict, capsys
) -> None:
    code = _preflight(_request(tmp_path, workspace, **{block: fields}), tmp_path)

    assert code == EXIT_CODES[Status.INVALID_SPEC]
    printed = capsys.readouterr().out
    assert f"{block}.{next(iter(fields))}" in printed
    assert CONFIG_PATH in printed
    assert not (tmp_path / "lock.json").exists()


def test_repeating_the_configured_values_is_allowed(
    tmp_path: Path, workspace: Workspace, config, capsys
) -> None:
    """The runbook's example repeats them. Repeating is not overriding."""
    request = _request(
        tmp_path,
        workspace,
        target={"remote": config.remote, "base_branch": config.base_branch},
        lock={"kind": "git-ref", "remote": config.remote, "namespace": config.lock_namespace},
        state={"kind": "git-ref", "remote": config.remote, "ref": config.state_ref},
    )

    code = _preflight(request, tmp_path)

    # It gets past the schema gate and stops at the next question — whether this checkout is the
    # configured repository — which is the one this test's workspace cannot be.
    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert "run_target.json" not in capsys.readouterr().out


def test_a_checkout_that_is_not_the_configured_repository_takes_no_lock(
    tmp_path: Path, workspace: Workspace, capsys
) -> None:
    """Checked before the lock: a container that cloned something else must not hold it."""
    workspace.git("remote", "add", "origin", "https://github.com/someone/else.git")

    code = _preflight(_request(tmp_path, workspace), tmp_path)

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert "someone/else" in capsys.readouterr().out
    assert not (tmp_path / "lock.json").exists()


def test_a_checkout_with_no_such_remote_is_refused(tmp_path: Path, workspace: Workspace) -> None:
    assert (
        _preflight(_request(tmp_path, workspace), tmp_path)
        == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    )
