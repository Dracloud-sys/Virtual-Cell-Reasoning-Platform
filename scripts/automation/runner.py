"""The entry point a scheduled run actually invokes.

    python -m automation preflight --request run-request.json

Everything above this module is pure, which is what makes it testable; this is where the facts
come from and where the process exit code is decided. The shape is deliberate: the agent calls
its GitHub tools, writes the **raw responses** into one JSON request file, and hands that file
here. The parsing, the filtering and the refusals then happen in code that a test can drive,
rather than in an agent's reading of a response it also summarised.

The exit code is the contract. ``0`` means, and only ever means, that work may begin; every
refusal has its own non-zero code (see :data:`~automation.outcomes.EXIT_CODES`) so a shell can
branch on the reason without parsing prose. ``--proceed-marker`` writes a file **only** on
``0`` — it exists so a caller, and the integration test, can assert that a refused run did not
go on to do anything.

Nothing here installs, pushes, or edits the repository. It decides, and it reports.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .environment import probe_environment
from .github_payloads import APPROVAL_LABEL, read_pull_requests, read_queue
from .gitrefs import GitRefLockStore, GitRefStateStore, LockUnavailable
from .locking import FileLockStore, InMemoryLockStore, LockStore
from .outcomes import Outcome, Status
from .preflight import GateInputs, Recheck, run_preflight
from .queue import QueueRead
from .revisions import RevisionInstruction

#: What `scripts/verify.py` needs before its result means anything.
REQUIRED_DEPENDENCIES: tuple[str, ...] = ("pydantic", "pytest", "ruff")


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@dataclass(frozen=True)
class RunRequest:
    """The raw material of one preflight decision, as written by the calling agent."""

    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> RunRequest:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @property
    def work_id(self) -> str:
        return str(self.raw.get("work_id") or "")

    def queue(self) -> QueueRead:
        return read_queue(
            self.raw.get("queue_pages") or [],
            approval_label=str(self.raw.get("approval_label") or APPROVAL_LABEL),
            error=self.raw.get("queue_error"),
        )

    def recheck_queue(self) -> QueueRead | None:
        pages = self.raw.get("recheck_queue_pages")
        if pages is None and not self.raw.get("recheck_queue_error"):
            return None
        return read_queue(
            pages or [],
            approval_label=str(self.raw.get("approval_label") or APPROVAL_LABEL),
            error=self.raw.get("recheck_queue_error"),
        )

    def pull_requests(self, key: str = "pull_requests") -> tuple:
        return read_pull_requests(self.raw.get(key) or [], work_id=self.work_id)

    def revisions(self) -> tuple[RevisionInstruction, ...]:
        return tuple(
            RevisionInstruction(
                identifier=str(item.get("identifier") or ""),
                approved_by=str(item.get("approved_by") or ""),
                target_pull_request=int(item.get("target_pull_request") or 0),
                target_head_sha=str(item.get("target_head_sha") or ""),
                approval_record_id=str(item.get("approval_record_id") or ""),
                content=str(item.get("content") or ""),
            )
            for item in self.raw.get("revisions") or []
        )

    def lock_store(self) -> LockStore:
        spec = self.raw.get("lock") or {}
        kind = str(spec.get("kind") or "memory")
        if kind == "git-ref":
            return GitRefLockStore(
                remote=str(spec["remote"]),
                workdir=Path(str(spec.get("workdir") or ".")),
                namespace=str(spec.get("namespace") or "refs/vcrp-locks"),
            )
        if kind == "file":
            return FileLockStore(Path(str(spec["directory"])))
        return InMemoryLockStore()

    def applied_revision_ids(self) -> frozenset[str]:
        spec = self.raw.get("state") or {}
        if str(spec.get("kind") or "none") != "git-ref":
            return frozenset(self.raw.get("applied_revision_ids") or ())
        store = GitRefStateStore(
            remote=str(spec["remote"]), workdir=Path(str(spec.get("workdir") or "."))
        )
        return store.load()


def build_inputs(request: RunRequest) -> GateInputs:
    """Turn a request into gate inputs, probing the live interpreter for the environment."""
    recheck_queue = request.recheck_queue()
    recheck = None
    if recheck_queue is not None:
        recheck = lambda: Recheck(  # noqa: E731 - a one-expression closure, not a function
            queue=recheck_queue,
            open_pull_requests=request.pull_requests("recheck_pull_requests"),
        )

    return GateInputs(
        work_id=request.work_id,
        queue=request.queue(),
        environment=probe_environment(
            version=sys.version_info[:3],
            dependencies=REQUIRED_DEPENDENCIES,
            importable=_importable,
        ),
        lock_store=request.lock_store(),
        open_pull_requests=request.pull_requests(),
        revisions=request.revisions(),
        applied_revision_ids=request.applied_revision_ids(),
        approvers=tuple(request.raw.get("approvers") or ()),
        existing_branches=tuple(request.raw.get("existing_branches") or ()),
        recheck=recheck,
        owner=str(request.raw.get("owner") or "scheduled-runner"),
    )


def report(outcome: Outcome, *, as_json: bool) -> str:
    if as_json:
        return json.dumps(
            {
                "status": outcome.status.value,
                "detail": outcome.detail,
                "evidence": dict(outcome.evidence),
                "exit_code": outcome.exit_code,
            },
            indent=2,
        )
    lines = [outcome.line()]
    lines.extend(f"  {key}: {value}" for key, value in sorted(outcome.evidence.items()))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m automation", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gate = sub.add_parser("preflight", help="decide whether a run may begin")
    gate.add_argument("--request", required=True, type=Path, help="JSON run request")
    gate.add_argument("--json", action="store_true", help="machine-readable report")
    gate.add_argument(
        "--proceed-marker",
        type=Path,
        help="write this file only if the gate proceeds; nothing is written on a refusal",
    )

    args = parser.parse_args(argv)

    try:
        request = RunRequest.load(args.request)
    except (OSError, json.JSONDecodeError) as error:
        outcome = Outcome(Status.BLOCKED_GITHUB_ACCESS, f"unreadable run request: {error}")
        print(report(outcome, as_json=args.json))
        return outcome.exit_code

    try:
        outcome = run_preflight(build_inputs(request))
    except LockUnavailable as error:
        outcome = Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))

    print(report(outcome, as_json=args.json))

    if outcome.proceeds and args.proceed_marker is not None:
        args.proceed_marker.write_text(report(outcome, as_json=True), encoding="utf-8")
    return outcome.exit_code
