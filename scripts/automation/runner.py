"""The commands a scheduled run invokes, and the exit codes it branches on.

    python scripts/automation/cli.py preflight --request phase1.json --token lock.json
    python scripts/automation/cli.py confirm --request phase2.json --token .automation/lock.json
    …implementation happens here…
    python scripts/automation/cli.py postflight --request p1.json --token lock.json --base main
    python scripts/automation/cli.py release --request phase1.json --token lock.json

Four commands, because the run has four moments where it can be wrong, and one process cannot
straddle them:

**preflight** reads the queue, validates the contract, and takes the lock. It does *not* grant
permission to work — it writes a lock token and stops.

**confirm** is the real re-read. The agent queries GitHub *again*, after the lock exists, and
submits those responses with the token. Only this command writes the proceed marker, and only
when the token matches, the evidence was captured after the lock was taken, and the world still
looks the way phase one decided about. The previous version parsed both snapshots out of one
file before locking, which is not a re-read at all.

**postflight** judges the finished change: real changed paths against the issue's own path
rules, kernel authorisation, `scripts/verify.py` in full, and recording the applied revision.
Nothing is pushed unless this exits 0.

**release** drops the lock using the token, so the process that took it does not have to be the
process that gives it back.

Exit code 0 means, and only ever means, that the step succeeded and the next one may begin.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .approvals import ApproverConfigError, load_approvers, parse_approvals
from .environment import probe_environment
from .github_payloads import APPROVAL_LABEL, SchemaError, read_pull_requests, read_queue
from .gitrefs import GitRefLockStore, GitRefStateStore, LockUnavailable, StateCorrupt
from .locking import FileLockStore, InMemoryLockStore, LockStore
from .outcomes import Outcome, Status
from .postflight import PostflightInputs, run_postflight
from .preflight import GateInputs, run_preflight
from .queue import QueueRead
from .tokens import LockToken, fingerprint_of

#: What `scripts/verify.py` needs before its result means anything.
REQUIRED_DEPENDENCIES: tuple[str, ...] = ("pydantic", "pytest", "ruff")


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@dataclass(frozen=True)
class RunRequest:
    """The raw material of one decision, as written by the calling agent."""

    raw: dict[str, Any]
    path: Path

    @classmethod
    def load(cls, path: Path) -> RunRequest:
        return cls(json.loads(path.read_text(encoding="utf-8")), path)

    @property
    def work_id(self) -> str:
        return str(self.raw.get("work_id") or "")

    @property
    def captured_at(self) -> str:
        return str(self.raw.get("captured_at") or "")

    def queue(self) -> QueueRead:
        return read_queue(
            self.raw.get("queue_pages") or [],
            approval_label=str(self.raw.get("approval_label") or APPROVAL_LABEL),
            error=self.raw.get("queue_error"),
        )

    def pull_requests(self) -> tuple:
        return read_pull_requests(self.raw.get("pull_requests") or [], work_id=self.work_id)

    def approvers(self, repo_root: Path) -> tuple[str, ...]:
        configured = self.raw.get("approvers_file")
        path = Path(configured) if configured else repo_root / "docs/operations/run_approvers.json"
        return load_approvers(path)

    def revisions(self, approvers: Sequence[str]) -> tuple[tuple, tuple]:
        return parse_approvals(self.raw.get("approvals") or [], approvers=approvers)

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

    def state_store(self) -> GitRefStateStore | None:
        spec = self.raw.get("state") or {}
        if str(spec.get("kind") or "none") != "git-ref":
            return None
        return GitRefStateStore(
            remote=str(spec["remote"]), workdir=Path(str(spec.get("workdir") or "."))
        )

    def applied_revision_ids(self) -> frozenset[str]:
        store = self.state_store()
        if store is None:
            return frozenset(self.raw.get("applied_revision_ids") or ())
        return store.load()


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load(path: Path) -> tuple[RunRequest | None, Outcome | None]:
    try:
        return RunRequest.load(path), None
    except (OSError, json.JSONDecodeError) as error:
        return None, Outcome(Status.BLOCKED_GITHUB_ACCESS, f"unreadable run request: {error}")


# --- phase one -------------------------------------------------------------------------------


def command_preflight(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None

    try:
        approvers = request.approvers(_repo_root())
        revisions, refused = request.revisions(approvers)
        applied = request.applied_revision_ids()
    except (ApproverConfigError, StateCorrupt) as error:
        return Outcome(Status.INVALID_SPEC, str(error))
    except (LockUnavailable, SchemaError) as error:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))

    try:
        pull_requests = request.pull_requests()
    except SchemaError as error:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))

    store = request.lock_store()
    owner = str(request.raw.get("owner") or f"scheduled-runner-{secrets.token_hex(8)}")

    outcome = run_preflight(
        GateInputs(
            work_id=request.work_id,
            queue=request.queue(),
            environment=probe_environment(
                version=sys.version_info[:3],
                dependencies=REQUIRED_DEPENDENCIES,
                importable=_importable,
            ),
            lock_store=store,
            open_pull_requests=pull_requests,
            revisions=revisions,
            applied_revision_ids=applied,
            approvers=approvers,
            existing_branches=tuple(request.raw.get("existing_branches") or ()),
            owner=owner,
        )
    )
    if refused and not outcome.proceeds:
        outcome = Outcome(
            outcome.status, outcome.detail + "; approvals refused: " + "; ".join(map(str, refused))
        )
    if not outcome.proceeds:
        return outcome

    issue = (request.queue().issues or ())[0]
    token = LockToken.mint(
        work_id=request.work_id,
        owner=owner,
        lock_sha=store.token_for(request.work_id) if hasattr(store, "token_for") else "local",
        lock_ref=store.ref(request.work_id) if hasattr(store, "ref") else "local",
        issue_number=issue.number,
        fingerprint=fingerprint_of(
            issue_number=issue.number, issue_body=issue.body, pull_requests=pull_requests
        ),
    )
    token.write(args.token)
    return Outcome(
        Status.READY_TO_IMPLEMENT,
        f"lock held for {request.work_id}; now re-read GitHub and run `confirm`",
        {**outcome.evidence, "token": str(args.token), "phase": "1 of 2"},
    )


# --- phase two -------------------------------------------------------------------------------


def command_confirm(args: argparse.Namespace) -> Outcome:
    """The real re-read: fresh responses, gathered after the lock, checked against phase one."""
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None

    try:
        token = LockToken.read(args.token)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return Outcome(Status.ALREADY_RUNNING, f"no usable lock token: {error}")

    if request.work_id != token.work_id:
        return Outcome(
            Status.WORK_ID_MISMATCH,
            f"the confirmation names {request.work_id!r}, the lock is for {token.work_id!r}",
        )
    if not request.captured_at:
        return Outcome(
            Status.BLOCKED_GITHUB_ACCESS,
            "the confirmation carries no captured_at, so it cannot be shown to postdate the lock",
        )
    if not token.captured_after(request.captured_at):
        return Outcome(
            Status.BLOCKED_GITHUB_ACCESS,
            f"the confirmation's evidence was captured at {request.captured_at}, before the lock "
            f"was taken at {token.acquired_at}; that is a stale snapshot, not a re-read",
        )

    fresh = request.queue()
    if not fresh.succeeded:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, f"the re-read did not succeed: {fresh.error}")
    issues = fresh.issues or ()
    if not issues:
        return Outcome(
            Status.NO_READY_WORK, "the approval was withdrawn while the run was starting"
        )
    if len(issues) > 1:
        return Outcome(Status.AMBIGUOUS_QUEUE, "a second issue was approved while the run started")
    if issues[0].number != token.issue_number:
        return Outcome(
            Status.NO_READY_WORK,
            f"issue #{token.issue_number} is no longer the approved item (#{issues[0].number} is)",
        )

    try:
        pull_requests = request.pull_requests()
    except SchemaError as error:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))

    now = fingerprint_of(
        issue_number=issues[0].number, issue_body=issues[0].body, pull_requests=pull_requests
    )
    if now != token.fingerprint:
        return Outcome(
            Status.AWAITING_REVIEW,
            "the issue or its pull requests changed between locking and confirming; phase one's "
            "decision was about a situation that no longer exists",
            {"phase1": token.fingerprint[:12], "phase2": now[:12]},
        )

    outcome = Outcome(
        Status.READY_TO_IMPLEMENT,
        f"confirmed against a re-read; implementing issue #{token.issue_number}",
        {"issue": str(token.issue_number), "phase": "2 of 2", "lock": token.lock_ref},
    )
    if args.proceed_marker is not None:
        args.proceed_marker.write_text(report(outcome, as_json=True), encoding="utf-8")
    return outcome


# --- after the work --------------------------------------------------------------------------


def command_postflight(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None

    try:
        token = LockToken.read(args.token)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return Outcome(Status.ALREADY_RUNNING, f"no usable lock token: {error}")

    queue = request.queue()
    if not queue.succeeded or not (queue.issues or ()):
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, "cannot re-read the issue this work is for")

    outcome = run_postflight(
        PostflightInputs(
            work_id=token.work_id,
            issue_body=(queue.issues or ())[0].body,
            base=args.base,
            workdir=Path(args.workdir),
            unchanged=tuple(args.unchanged),
            revision_id=args.revision or None,
            recorder=request.state_store(),
        )
    )
    if not outcome.proceeds and args.release_on_failure:
        _release(request, token)
    return outcome


def _release(request: RunRequest, token: LockToken) -> bool:
    store = request.lock_store()
    if isinstance(store, GitRefLockStore):
        return store.release(token.work_id, token.owner, token=token.lock_sha)
    return store.release(token.work_id, token.owner)


def command_release(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None
    try:
        token = LockToken.read(args.token)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return Outcome(Status.ALREADY_RUNNING, f"no usable lock token: {error}")

    if _release(request, token):
        args.token.unlink(missing_ok=True)
        return Outcome(Status.READY_TO_IMPLEMENT, f"released the lock on {token.work_id}")
    return Outcome(
        Status.ALREADY_RUNNING,
        f"the lock on {token.work_id} was not ours to release, or is already gone",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/automation/cli.py", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("preflight", "phase 1: read the queue, validate, take the lock"),
        ("confirm", "phase 2: submit a re-read and receive permission to work"),
        ("postflight", "after the work: enforce scope and verification before pushing"),
        ("release", "give the lock back"),
    ):
        step = sub.add_parser(name, help=help_text)
        step.add_argument("--request", required=True, type=Path)
        step.add_argument("--token", required=True, type=Path)
        step.add_argument("--json", action="store_true")
        if name == "confirm":
            step.add_argument("--proceed-marker", type=Path)
        if name == "postflight":
            step.add_argument("--base", required=True)
            step.add_argument("--workdir", default=".")
            step.add_argument("--unchanged", action="append", default=[])
            step.add_argument("--revision", default="")
            step.add_argument("--release-on-failure", action="store_true", default=True)

    args = parser.parse_args(argv)
    handlers = {
        "preflight": command_preflight,
        "confirm": command_confirm,
        "postflight": command_postflight,
        "release": command_release,
    }
    try:
        outcome = handlers[args.command](args)
    except LockUnavailable as error:
        outcome = Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))
    except StateCorrupt as error:
        outcome = Outcome(Status.INVALID_SPEC, f"durable state is unusable: {error}")

    print(report(outcome, as_json=args.json))
    return outcome.exit_code
