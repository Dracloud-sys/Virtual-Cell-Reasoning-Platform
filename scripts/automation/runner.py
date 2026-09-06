"""The commands a scheduled run invokes, and the exit codes it branches on.

    python scripts/automation/cli.py preflight  --request p1.json --token lock.json
    python scripts/automation/cli.py confirm    --request p2.json --token lock.json \
        --confirmation confirm.json
    #   ...the implementation happens here...
    python scripts/automation/cli.py postflight --request p2.json --token lock.json \
        --confirmation confirm.json --base origin/main
    #   ...the push happens here...
    python scripts/automation/cli.py finalize   --request p3.json --token lock.json \
        --confirmation confirm.json --branch claude/... --pushed-sha <sha>

Five commands, because the run has five moments where it can be wrong, and one process cannot
straddle them. What ties them together is not the sequence — a sequence is a suggestion — but a
chain each step has to present:

* **the remote lock.** Every step re-reads the lock ref and compares it against the token's
  `lock_sha`. A token file proves what this run once took; it says nothing about now, and
  another run can delete the ref and take it while that file still looks convincing.
* **the confirmation artifact.** `postflight` refuses without one bound to the same token, so
  `preflight → postflight` cannot skip the re-read.
* **the token's own copy of the decision.** The issue body hash and the selected revision live
  in the token, so widening `allowed paths` in the request file after phase one changes nothing.

And two rules about giving the lock back. A `confirm` that refuses **releases the lock** and
clears the token and marker, because otherwise a withdrawn label leaves every later run
reporting `ALREADY_RUNNING`. A revision is recorded **only by `finalize`**, after the remote
branch is shown to carry the exact commit that passed verification — recording before the push
means a failed push leaves "already applied" true and the fix absent.

Exit code 0 means the step succeeded and the next may begin. Nothing else does.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import subprocess
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
from .tokens import BoundRevision, Confirmation, LockToken, fingerprint_of, sha256_of

#: What `scripts/verify.py` needs before its result means anything.
REQUIRED_DEPENDENCIES: tuple[str, ...] = ("pydantic", "pytest", "ruff")

#: Committed, and *only* here. The request file is written by the agent, so an approver list it
#: could point at is an approver list it could write itself.
APPROVERS_PATH = "docs/operations/run_approvers.json"


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class RequestSchemaError(ValueError):
    """The request asks for something a request is not allowed to decide."""


@dataclass(frozen=True)
class RunRequest:
    """The raw material of one decision, as written by the calling agent."""

    raw: dict[str, Any]
    path: Path

    @classmethod
    def load(cls, path: Path) -> RunRequest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "approvers_file" in raw or "approvers" in raw:
            # Refused rather than ignored: a request that tried to name its own approvers was
            # written by something that believed it could, and that belief is the finding.
            raise RequestSchemaError(
                "a run request may not choose its approvers; they come from "
                f"{APPROVERS_PATH}, which changes only by a reviewed commit"
            )
        return cls(raw, path)

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

    def revisions(self, approvers: Sequence[str]) -> tuple[tuple, tuple]:
        return parse_approvals(self.raw.get("approvals") or [], approvers=approvers)

    def branches(self) -> tuple[str, ...]:
        return tuple(self.raw.get("existing_branches") or ())

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
    except RequestSchemaError as error:
        return None, Outcome(Status.INVALID_SPEC, str(error))
    except (OSError, json.JSONDecodeError) as error:
        return None, Outcome(Status.BLOCKED_GITHUB_ACCESS, f"unreadable run request: {error}")


def _read_token(path: Path) -> tuple[LockToken | None, Outcome | None]:
    try:
        return LockToken.read(path), None
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        return None, Outcome(Status.ALREADY_RUNNING, f"no usable lock token: {error}")


def _still_ours(store: LockStore, token: LockToken) -> Outcome | None:
    """The question a local token cannot answer: does the remote still hold *our* lock?"""
    try:
        held = store.held_token(token.work_id)
    except LockUnavailable as error:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, f"cannot verify the lock: {error}")
    if held is None:
        return Outcome(
            Status.ALREADY_RUNNING,
            f"the lock on {token.work_id} is gone; this run no longer holds it",
        )
    if held != token.lock_sha:
        return Outcome(
            Status.ALREADY_RUNNING,
            f"the lock on {token.work_id} was replaced by another run "
            f"({held[:12]} != {token.lock_sha[:12]})",
        )
    return None


def _release(store: LockStore, token: LockToken) -> bool:
    if isinstance(store, GitRefLockStore):
        return store.release(token.work_id, token.owner, token=token.lock_sha)
    return store.release(token.work_id, token.owner, token=token.lock_sha)


def _abandon(store: LockStore, token: LockToken, refusal: Outcome, *paths: Path) -> Outcome:
    """Refuse, and hand the lock back so the next run is not blocked by a failure that ended."""
    try:
        released = _release(store, token)
    except LockUnavailable as error:
        return Outcome(
            refusal.status,
            f"{refusal.detail}; AND the lock could not be released: {error}",
            {**refusal.evidence, "lock_released": "no"},
        )
    for path in paths:
        path.unlink(missing_ok=True)
    if not released:
        return Outcome(
            refusal.status,
            f"{refusal.detail}; AND the lock was not ours to release, so it may be stuck",
            {**refusal.evidence, "lock_released": "no"},
        )
    return Outcome(refusal.status, refusal.detail, {**refusal.evidence, "lock_released": "yes"})


# --- phase one -------------------------------------------------------------------------------


def command_preflight(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None

    try:
        approvers = load_approvers(_repo_root() / APPROVERS_PATH)
        revisions, refused = request.revisions(approvers)
        applied = request.applied_revision_ids()
        pull_requests = request.pull_requests()
    except (ApproverConfigError, StateCorrupt) as error:
        return Outcome(Status.INVALID_SPEC, str(error))
    except (LockUnavailable, SchemaError) as error:
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
            existing_branches=request.branches(),
            owner=owner,
        )
    )
    if not outcome.proceeds:
        if refused:
            return Outcome(
                outcome.status,
                outcome.detail + "; approvals refused: " + "; ".join(map(str, refused)),
                outcome.evidence,
            )
        return outcome

    issue = (request.queue().issues or ())[0]
    chosen = outcome.evidence.get("revision")
    bound = next((BoundRevision.of(r) for r in revisions if r.approval_record_id == chosen), None)
    token = LockToken.mint(
        work_id=request.work_id,
        owner=owner,
        lock_sha=store.token_for(request.work_id) or "",
        lock_ref=store.ref(request.work_id) if hasattr(store, "ref") else "local",
        issue_number=issue.number,
        issue_body=issue.body,
        fingerprint=fingerprint_of(
            issue_number=issue.number, issue_body=issue.body, pull_requests=pull_requests
        ),
        pull_requests=tuple(f"{pr.number}:{pr.head_sha}" for pr in pull_requests),
        existing_branches=request.branches(),
        revision=bound,
    )
    token.write(args.token)
    return Outcome(
        Status.READY_TO_IMPLEMENT,
        f"lock held for {request.work_id}; now re-read GitHub and run `confirm`",
        {**outcome.evidence, "token": str(args.token), "phase": "1 of 2"},
    )


# --- phase two -------------------------------------------------------------------------------


def _freshness_problem(token: LockToken, request: RunRequest) -> str | None:
    """Whether the confirmation's evidence can be shown not to predate the lock.

    `captured_at` is a string the agent wrote; it asserts freshness, it does not prove it. The
    file's own mtime is checked as well, which is weaker still but catches the case the
    assertion cannot: a phase-two file prepared before the lock was ever taken.
    """
    if not request.captured_at:
        return "carries no captured_at, so it does not even assert that it postdates the lock"
    if not token.captured_after(request.captured_at):
        return (
            f"asserts it was captured at {request.captured_at}, before the lock was taken at "
            f"{token.acquired_at}; that is a stale snapshot, not a re-read"
        )
    try:
        written = request.path.stat().st_mtime
    except OSError:
        return None
    if written < token.acquired_epoch():
        return "was written before the lock was taken, so it cannot be a re-read of anything"
    return None


def command_confirm(args: argparse.Namespace) -> Outcome:
    """The real re-read: fresh responses, gathered after the lock, checked against phase one."""
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None

    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store = request.lock_store()
    lost = _still_ours(store, token)
    if lost is not None:
        # Not ours to release, and not ours to clean up either.
        return lost

    cleanup = [args.token] + ([args.proceed_marker] if args.proceed_marker else [])

    def refuse(status: Status, detail: str, evidence: dict[str, str] | None = None) -> Outcome:
        return _abandon(store, token, Outcome(status, detail, evidence or {}), *cleanup)

    if request.work_id != token.work_id:
        return refuse(
            Status.WORK_ID_MISMATCH,
            f"the confirmation names {request.work_id!r}, the lock is for {token.work_id!r}",
        )

    stale = _freshness_problem(token, request)
    if stale:
        return refuse(Status.BLOCKED_GITHUB_ACCESS, f"the confirmation {stale}")

    fresh = request.queue()
    if not fresh.succeeded:
        return refuse(Status.BLOCKED_GITHUB_ACCESS, f"the re-read did not succeed: {fresh.error}")
    issues = fresh.issues or ()
    if not issues:
        return refuse(Status.NO_READY_WORK, "the approval was withdrawn while the run was starting")
    if len(issues) > 1:
        return refuse(
            Status.AMBIGUOUS_QUEUE, "a second issue was approved while the run was starting"
        )
    if issues[0].number != token.issue_number:
        return refuse(
            Status.NO_READY_WORK,
            f"issue #{token.issue_number} is no longer the approved item (#{issues[0].number} is)",
        )

    try:
        pull_requests = request.pull_requests()
        approvers = load_approvers(_repo_root() / APPROVERS_PATH)
        revisions, _ = request.revisions(approvers)
    except SchemaError as error:
        return refuse(Status.BLOCKED_GITHUB_ACCESS, str(error))
    except ApproverConfigError as error:
        return refuse(Status.INVALID_SPEC, str(error))

    now = fingerprint_of(
        issue_number=issues[0].number, issue_body=issues[0].body, pull_requests=pull_requests
    )
    if now != token.fingerprint:
        return refuse(
            Status.AWAITING_REVIEW,
            "the issue or its pull requests changed between locking and confirming; phase one's "
            "decision was about a situation that no longer exists",
            {"phase1": token.fingerprint[:12], "phase2": now[:12]},
        )

    # The bound revision has to still be a live approval in the freshly parsed records.
    if token.revision is not None and not any(token.revision.matches(r) for r in revisions):
        return refuse(
            Status.AWAITING_REVIEW,
            f"the approval {token.revision.record_id} phase one selected is no longer present, "
            "unchanged, in the re-read",
        )

    appeared = tuple(
        branch
        for branch in request.branches()
        if branch.startswith(f"claude/{token.work_id}") and branch not in token.existing_branches
    )
    if appeared:
        return refuse(
            Status.AWAITING_REVIEW,
            f"branch {appeared[0]} appeared after the lock was taken; another run may be part "
            "way through this work",
            {"branch": appeared[0]},
        )

    linked = [pr for pr in pull_requests if pr.work_id == token.work_id]
    confirmation = Confirmation.of(
        token,
        issue_body=issues[0].body,
        pull_request=linked[0].number if linked else None,
        pull_request_head_sha=linked[0].head_sha if linked else "",
    )
    confirmation.write(args.confirmation)

    outcome = Outcome(
        Status.READY_TO_IMPLEMENT,
        f"confirmed against a re-read; implementing issue #{token.issue_number}",
        {
            "issue": str(token.issue_number),
            "phase": "2 of 2",
            "lock": token.lock_ref,
            "confirmation": str(args.confirmation),
            "resume_branch": token.existing_branches[0] if token.existing_branches else "",
        },
    )
    if args.proceed_marker is not None:
        args.proceed_marker.write_text(report(outcome, as_json=True), encoding="utf-8")
    return outcome


# --- after the work --------------------------------------------------------------------------


def _confirmed(
    args: argparse.Namespace, token: LockToken
) -> tuple[Confirmation | None, Outcome | None]:
    try:
        confirmation = Confirmation.read(args.confirmation)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        return None, Outcome(
            Status.AWAITING_REVIEW,
            f"no usable confirmation artifact ({error}); `confirm` has not granted permission "
            "for this run",
        )
    problem = confirmation.problem_against(token)
    if problem:
        return None, Outcome(Status.AWAITING_REVIEW, problem)
    return confirmation, None


def command_postflight(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None

    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store = request.lock_store()
    lost = _still_ours(store, token)
    if lost is not None:
        return lost

    confirmation, failure = _confirmed(args, token)
    if failure is not None:
        return failure
    assert confirmation is not None

    queue = request.queue()
    if not queue.succeeded or not (queue.issues or ()):
        return _abandon(
            store,
            token,
            Outcome(Status.BLOCKED_GITHUB_ACCESS, "cannot re-read the issue this work is for"),
            args.token,
            args.confirmation,
        )
    body = (queue.issues or ())[0].body
    if sha256_of(body) != confirmation.confirmed_issue_body_sha:
        # The path policy comes from the body the chain agreed on. Widening `allowed paths` in
        # a request file after phase one is exactly the bypass this closes. The lock still comes
        # back: this run is over either way, and a stuck lock would punish the next one.
        return _abandon(
            store,
            token,
            Outcome(
                Status.BLOCKED_SCOPE,
                "the issue body supplied to postflight is not the one that was confirmed; the "
                "path policy would come from a contract nothing validated",
            ),
            args.token,
            args.confirmation,
        )

    outcome = run_postflight(
        PostflightInputs(
            work_id=token.work_id,
            issue_body=body,
            base=args.base,
            workdir=Path(args.workdir),
            unchanged=tuple(args.unchanged),
        )
    )
    if not outcome.proceeds:
        return _abandon(store, token, outcome, args.token, args.confirmation)

    head = _rev(Path(args.workdir), "HEAD")
    Confirmation(**{**confirmation.__dict__, "verified_head": head or ""}).write(args.confirmation)
    return outcome.with_evidence(verified_head=head or "unknown", next_step="push, then finalize")


def _rev(workdir: Path, ref: str) -> str | None:
    proc = subprocess.run(["git", "rev-parse", ref], cwd=workdir, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def command_finalize(args: argparse.Namespace) -> Outcome:
    """After the push: prove the remote carries the verified commit, then record and release."""
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None

    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store = request.lock_store()
    lost = _still_ours(store, token)
    if lost is not None:
        return lost

    confirmation, failure = _confirmed(args, token)
    if failure is not None:
        return failure
    assert confirmation is not None

    if not confirmation.verified_head:
        return Outcome(
            Status.BLOCKED_SCOPE,
            "postflight has not verified a commit for this run; there is nothing to finalize",
        )
    if args.pushed_sha != confirmation.verified_head:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"the branch carries {args.pushed_sha[:12]} but verification passed on "
            f"{confirmation.verified_head[:12]}; the pushed commit was never checked",
        )

    if token.revision is not None:
        recorder = request.state_store()
        if recorder is None:
            return Outcome(
                Status.BLOCKED_GITHUB_ACCESS,
                f"revision {token.revision.record_id} was applied and pushed but there is no "
                "durable store to record it in; the next run would apply it again",
            )
        try:
            recorder.record(token.revision.record_id)
        except (LockUnavailable, StateCorrupt) as error:
            return Outcome(
                Status.BLOCKED_GITHUB_ACCESS,
                f"could not record revision {token.revision.record_id}: {error}",
            )

    released = _release(store, token)
    args.token.unlink(missing_ok=True)
    args.confirmation.unlink(missing_ok=True)
    return Outcome(
        Status.READY_TO_IMPLEMENT,
        f"{args.pushed_sha[:12]} is on the remote, verified; work item {token.work_id} complete",
        {
            "recorded_revision": token.revision.record_id if token.revision else "none",
            "lock_released": "yes" if released else "no",
        },
    )


def command_release(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args.request)
    if failure is not None:
        return failure
    assert request is not None
    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store = request.lock_store()
    lost = _still_ours(store, token)
    if lost is not None:
        args.token.unlink(missing_ok=True)
        return lost

    if _release(store, token):
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
        ("finalize", "after the push: prove the remote has the verified commit, record, release"),
        ("release", "give the lock back"),
    ):
        step = sub.add_parser(name, help=help_text)
        step.add_argument("--request", required=True, type=Path)
        step.add_argument("--token", required=True, type=Path)
        step.add_argument("--json", action="store_true")
        if name in {"confirm", "postflight", "finalize"}:
            step.add_argument("--confirmation", required=True, type=Path)
        if name == "confirm":
            step.add_argument("--proceed-marker", type=Path)
        if name == "postflight":
            step.add_argument("--base", required=True)
            step.add_argument("--workdir", default=".")
            step.add_argument("--unchanged", action="append", default=[])
        if name == "finalize":
            step.add_argument("--branch", default="")
            step.add_argument("--pushed-sha", required=True)

    args = parser.parse_args(argv)
    handlers = {
        "preflight": command_preflight,
        "confirm": command_confirm,
        "postflight": command_postflight,
        "finalize": command_finalize,
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
