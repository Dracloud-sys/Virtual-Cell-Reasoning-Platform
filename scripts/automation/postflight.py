"""The gate between "the work is done" and "the work is pushed".

Preflight decides whether a run may *begin*. Nothing decided whether what it produced was
allowed — `PathPolicy` existed and had tests, and no caller ever handed it a real diff, so
`BLOCKED_SCOPE` was a status the entry point could not actually reach. A rule that only exists
in a unit test is a rule the run does not have.

This runs after the implementation and before the push, and every check is on the real thing:

* **the actual changed paths**, from ``git diff --name-status -M base...HEAD`` — with renames
  detected, so both ends are judged. Moving a file out of the kernel is a kernel change, and it
  is invisible to anything that only looks at where the file landed;
* **the issue's own allowed and forbidden paths**, parsed from the body the gate validated;
* **kernel authorisation**, which stays closed unless the issue's box says otherwise, whatever
  the path lists happen to say;
* **`scripts/verify.py` in full**, exit code and all — including its refusal to compare a dirty
  tree, so "the diff was checked" and "the diff was checked against what will be pushed" are
  the same statement;
* **the applied revision id**, recorded in durable state *after* everything else passes.

On any failure the run must not push, and the lock is released so the next run is not blocked
by a failure that already ended.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .outcomes import Outcome, Status
from .scope import PathChange, PathPolicy, parse_path_policy
from .spec_contract import validate_spec


def changed_paths(base: str, *, workdir: Path, head: str = "HEAD") -> tuple[PathChange, ...]:
    """Every path the diff touches, with renames carrying where they came from."""
    proc = subprocess.run(
        ["git", "diff", "--name-status", "-M", f"{base}...{head}"],
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cannot diff {base}...{head}: {proc.stderr.strip()}")

    changes: list[PathChange] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        status = fields[0]
        if status.startswith("R") and len(fields) >= 3:
            changes.append(PathChange(path=fields[2], previous_path=fields[1]))
        elif len(fields) >= 2:
            changes.append(PathChange(path=fields[1]))
    return tuple(changes)


@dataclass(frozen=True)
class PostflightInputs:
    """What the gate needs to judge a finished change."""

    work_id: str
    issue_body: str
    base: str
    workdir: Path
    #: Extra byte-identical assertions this work item promised, e.g. src/virtualcell/.
    unchanged: tuple[str, ...] = ()
    revision_id: str | None = None
    #: Injected so the tests can drive the failure paths without a 10-second suite run.
    verify: object | None = None
    recorder: object | None = None
    evidence: dict[str, str] = field(default_factory=dict)


def run_verify(workdir: Path, base: str, unchanged: Sequence[str] = ()) -> tuple[int, str]:
    """`scripts/verify.py`, run as the process it is, with its exit code kept intact."""
    argv = [sys.executable, "scripts/verify.py", "--base", base]
    for path in unchanged:
        argv += ["--unchanged", path]
    proc = subprocess.run(argv, cwd=workdir, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def run_postflight(inputs: PostflightInputs) -> Outcome:
    """Decide whether the finished work may be pushed."""
    report = validate_spec(inputs.issue_body)
    if not report.ok:
        return Outcome(
            Status.INVALID_SPEC,
            "the issue stopped being executable while the work was in flight: "
            + " ".join(report.problems),
        )

    try:
        changes = changed_paths(inputs.base, workdir=inputs.workdir)
    except RuntimeError as error:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))

    policy: PathPolicy = parse_path_policy(
        inputs.issue_body, kernel_authorized=report.kernel_authorized
    )
    verdict = policy.verdict(changes)
    if not verdict.proceeds:
        return verdict.with_evidence(
            changed_paths=str(len(changes)),
            kernel_authorized="yes" if report.kernel_authorized else "no",
        )

    verify = inputs.verify or run_verify
    code, output = verify(inputs.workdir, inputs.base, inputs.unchanged)  # type: ignore[operator]
    if code != 0:
        tail = " / ".join(line.strip() for line in output.strip().splitlines()[-3:])
        return Outcome(
            Status.BLOCKED_ENVIRONMENT if code not in (1, 2) else Status.BLOCKED_SCOPE,
            f"verification did not pass (exit {code}): {tail}",
            {"verify_exit": str(code)},
        )

    evidence = {
        "changed_paths": str(len(changes)),
        "kernel_authorized": "yes" if report.kernel_authorized else "no",
        "verify_exit": "0",
    }

    if inputs.revision_id:
        recorder = inputs.recorder
        if recorder is None:
            return Outcome(
                Status.BLOCKED_GITHUB_ACCESS,
                f"revision {inputs.revision_id} was applied but there is no durable store to "
                "record it in; the next run would apply it again",
            )
        try:
            recorder.record(inputs.revision_id)  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - any failure here means "do not push"
            return Outcome(
                Status.BLOCKED_GITHUB_ACCESS,
                f"could not record revision {inputs.revision_id}: {error}",
            )
        evidence["recorded_revision"] = inputs.revision_id

    return Outcome(
        Status.READY_TO_IMPLEMENT,
        f"{len(changes)} changed path(s) authorised and verification passed; safe to push",
        evidence,
    )
