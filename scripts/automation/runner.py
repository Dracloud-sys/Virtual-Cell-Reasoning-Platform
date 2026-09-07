"""The commands a scheduled run invokes, and the exit codes it branches on.

    python scripts/automation/cli.py preflight  --request p1.json --token lock.json
    python scripts/automation/cli.py confirm    --request p2.json --token lock.json \
        --confirmation confirm.json
    #   ...the implementation happens here...
    python scripts/automation/cli.py postflight --request p2.json --token lock.json \
        --confirmation confirm.json
    #   ...the push happens here...
    python scripts/automation/cli.py finalize   --request p3.json --token lock.json \
        --confirmation confirm.json

Five commands, because the run has five moments where it can be wrong, and one process cannot
straddle them. What ties them together is not the sequence — a sequence is a suggestion — but a
chain each step has to present:

* **the remote lock.** Every step re-reads the lock ref and compares it against the token's
  `lock_sha`. A token file proves what this run once took; it says nothing about now, and
  another run can delete the ref and take it while that file still looks convincing.
* **the confirmation artifact.** `postflight` refuses without one bound to the same token, so
  `preflight → postflight` cannot skip the re-read.
* **the token's own copy of the decision.** The issue body hash, the selected revision, and the
  branch, remote and base SHA live in the token, so widening `allowed paths` in the request file
  after phase one changes nothing, and neither does naming a different base or branch.

Two things this file will not take the caller's word for. The **base** is resolved from the
remote at phase one and stored as a full SHA, because `postflight --base HEAD~1` on a resumed
branch inspects the last commit and calls the three before it unchanged. And the **pushed
commit** is read with `git ls-remote`, because a `--pushed-sha` from the caller's own
`git rev-parse HEAD` is equally true when the push failed, went elsewhere, or never ran.

And three rules about giving the lock back. A `confirm` that refuses **releases the lock** and
clears the token and marker, because otherwise a withdrawn label leaves every later run
reporting `ALREADY_RUNNING`. A revision is recorded **only by `finalize`**, after the remote
branch is shown to carry the exact commit that passed verification — recording before the push
means a failed push leaves "already applied" true and the fix absent. And a `finalize` whose
release **fails** exits non-zero and keeps the token, because deleting the artifacts needed to
retry the release, and calling that success, strands the lock permanently.

Exit code 0 means the step succeeded and the next may begin. Nothing else does.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import secrets
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .approvals import ApproverConfigError, load_approvers, parse_approvals
from .completion import CompletionInputs, check_completion
from .environment import probe_environment
from .github_payloads import (
    APPROVAL_LABEL,
    SchemaError,
    read_open_pull_requests,
    read_pull_requests,
    read_queue,
)
from .gitrefs import (
    GitRefLockStore,
    GitRefStateStore,
    LockCorrupt,
    LockUnavailable,
    StateCorrupt,
    remote_head,
)
from .locking import FileLockStore, InMemoryLockStore, LockStore
from .outcomes import Outcome, Status
from .postflight import PostflightInputs, run_postflight
from .preflight import GateInputs, run_preflight
from .production import (
    CONFIG_PATH,
    ProductionTarget,
    TargetConfigError,
    checkout_problem,
    load_target,
)
from .queue import QueueRead
from .tokens import (
    BoundRevision,
    BoundTarget,
    Confirmation,
    LockToken,
    fingerprint_of,
    sha256_of,
)

#: What `scripts/verify.py` needs before its result means anything.
REQUIRED_DEPENDENCIES: tuple[str, ...] = ("pydantic", "pytest", "ruff")

#: Committed, and *only* here. The request file is written by the agent, so an approver list it
#: could point at is an approver list it could write itself.
APPROVERS_PATH = "docs/operations/run_approvers.json"

#: The one lock a scheduled run may use. `file` and `memory` are visible to one container, and a
#: scheduled run gets a container to itself, so falling back to either is not a weaker lock — it
#: is no lock, silently, from a missing line in a JSON file.
PRODUCTION_LOCK_KIND = "git-ref"

#: Values the committed production target decides. A request may repeat them; it may not differ.
#: Written as (block, field, what the config says), because "the agent chose the remote it would
#: then be checked against" is the whole bug this closes.
FROZEN_BY_CONFIG: tuple[tuple[str, str, str], ...] = (
    ("target", "remote", "remote"),
    ("target", "base_branch", "base_branch"),
    ("target", "repository", "repository"),
    ("lock", "kind", ""),
    ("lock", "remote", "remote"),
    ("lock", "namespace", "lock_namespace"),
    ("state", "kind", ""),
    ("state", "remote", "remote"),
    ("state", "ref", "state_ref"),
)

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


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
    #: Test and development only, and set by a command-line flag rather than by the request, so
    #: the file the agent writes cannot grant itself a lock nobody else can see.
    allow_local_stores: bool = False
    #: The committed production target. None only under --development.
    config: ProductionTarget | None = None

    @classmethod
    def load(cls, path: Path, *, allow_local_stores: bool = False) -> RunRequest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "approvers_file" in raw or "approvers" in raw:
            # Refused rather than ignored: a request that tried to name its own approvers was
            # written by something that believed it could, and that belief is the finding.
            raise RequestSchemaError(
                "a run request may not choose its approvers; they come from "
                f"{APPROVERS_PATH}, which changes only by a reviewed commit"
            )
        config = None if allow_local_stores else load_target(_repo_root() / CONFIG_PATH)
        request = cls(raw, path, allow_local_stores, config)
        request._refuse_overrides()
        return request

    def _refuse_overrides(self) -> None:
        """A request may repeat what the committed config says. It may not differ from it.

        This is the same rule as the approver list, for the same reason: reading the base "off
        the remote" proves nothing if the caller picked the remote.
        """
        if self.config is None:
            return
        for block, field, attribute in FROZEN_BY_CONFIG:
            stated = (self.raw.get(block) or {}).get(field)
            if stated is None:
                continue
            expected = getattr(self.config, attribute) if attribute else PRODUCTION_LOCK_KIND
            if str(stated) != expected:
                raise RequestSchemaError(
                    f"a run request may not choose {block}.{field}: it says {stated!r} and "
                    f"{CONFIG_PATH} says {expected!r}, which changes only by a reviewed commit"
                )

    @property
    def work_id(self) -> str:
        return str(self.raw.get("work_id") or "")

    @property
    def workdir(self) -> Path:
        return Path(str(self.raw.get("workdir") or "."))

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
        """The lock, or a refusal. There is no default.

        The previous version defaulted to :class:`InMemoryLockStore`, which meant a run request
        that simply omitted its `lock` field ran with a lock private to its own process — and
        looked, in every report it wrote, exactly like a run that held a real one. A store that
        no other container can see is not a weak lock; it is the absence of one.
        """
        if self.config is not None:
            return GitRefLockStore(
                remote=self.config.remote,
                workdir=self.workdir,
                namespace=self.config.lock_namespace,
            )
        spec = self.raw.get("lock") or {}
        kind = str(spec.get("kind") or "")
        if kind == PRODUCTION_LOCK_KIND:
            try:
                return GitRefLockStore(
                    remote=str(spec["remote"]),
                    workdir=Path(str(spec.get("workdir") or self.workdir)),
                    namespace=str(spec.get("namespace") or GitRefLockStore.namespace),
                )
            except KeyError as error:
                raise RequestSchemaError(f"the git-ref lock names no {error}") from error
        if kind in {"file", "memory"}:
            if not self.allow_local_stores:
                raise RequestSchemaError(
                    f"lock kind {kind!r} is visible to one container only; a scheduled run needs "
                    f"{PRODUCTION_LOCK_KIND}. Pass --development to use it in a test"
                )
            if kind == "memory":
                return InMemoryLockStore()
            return FileLockStore(Path(str(spec["directory"])))
        raise RequestSchemaError(
            f"no usable lock: kind {kind or '(missing)'!r} is not {PRODUCTION_LOCK_KIND}. A "
            "missing or misspelled lock is a run with no mutual exclusion at all"
        )

    def state_store(self) -> GitRefStateStore | None:
        """The durable memory of which revisions have been carried out, or None if unconfigured.

        None is only survivable when the run has no revision to record; `preflight` refuses the
        combination rather than letting `finalize` discover it after the push.
        """
        if self.config is not None:
            return GitRefStateStore(
                remote=self.config.remote, workdir=self.workdir, ref=self.config.state_ref
            )
        spec = self.raw.get("state") or {}
        kind = str(spec.get("kind") or "")
        if kind == "":
            return None
        if kind != "git-ref":
            raise RequestSchemaError(f"state kind {kind!r} is not durable across containers")
        try:
            return GitRefStateStore(
                remote=str(spec["remote"]), workdir=Path(str(spec.get("workdir") or self.workdir))
            )
        except KeyError as error:
            raise RequestSchemaError(f"the git-ref state store names no {error}") from error

    def applied_revision_ids(self) -> frozenset[str]:
        store = self.state_store()
        if store is not None:
            return store.load()
        if self.raw.get("applied_revision_ids"):
            # Unconditional, development included: "this was already done" is the one answer that
            # makes a run skip work, so it may never come from the file the agent writes.
            raise RequestSchemaError(
                "a run request may not declare which revisions have already been applied; that "
                "comes from the durable state store"
            )
        return frozenset(self.raw.get("applied_revision_ids") or ())

    def declared_target(self) -> dict[str, str]:
        return {str(k): str(v) for k, v in (self.raw.get("target") or {}).items()}


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


def _load(args: argparse.Namespace) -> tuple[RunRequest | None, Outcome | None]:
    try:
        request = RunRequest.load(
            args.request, allow_local_stores=getattr(args, "development", False)
        )
    except (RequestSchemaError, TargetConfigError) as error:
        return None, Outcome(Status.INVALID_SPEC, str(error))
    except (OSError, json.JSONDecodeError) as error:
        return None, Outcome(Status.BLOCKED_GITHUB_ACCESS, f"unreadable run request: {error}")
    return request, None


def _store(request: RunRequest) -> tuple[LockStore | None, Outcome | None]:
    """The lock, or the reason there is none. Never a fallback nobody asked for."""
    try:
        return request.lock_store(), None
    except RequestSchemaError as error:
        return None, Outcome(Status.INVALID_SPEC, str(error))
    except OSError as error:
        return None, Outcome(Status.BLOCKED_GITHUB_ACCESS, f"cannot reach the lock store: {error}")


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


def _commit_present(workdir: Path, sha: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=workdir, capture_output=True, text=True
    )
    return proc.returncode == 0


def _effective_target(request: RunRequest) -> dict[str, str]:
    """The target's fields, with the committed config overriding anything the request says."""
    spec = dict(request.declared_target())
    if request.config is not None:
        spec |= {
            "remote": request.config.remote,
            "base_branch": request.config.base_branch,
            "repository": request.config.repository,
        }
    return spec


def _branch_prefix(request: RunRequest) -> str:
    return request.config.branch_prefix if request.config is not None else "claude/"


def _target_shape(request: RunRequest) -> Outcome | None:
    """What can be checked before the lock: the branch, and that this is the right checkout.

    The checkout identity belongs here rather than after the lock. It costs one local `git
    remote get-url`, it does not depend on anything the queue says, and a container that cloned
    a different repository must not be the one that takes the production lock.
    """
    spec = _effective_target(request)
    required = ("remote", "branch", "base_branch")
    if not all(spec.get(field) for field in required):
        missing = ", ".join(f"target.{f}" for f in required if not spec.get(f))
        return Outcome(
            Status.INVALID_SPEC,
            f"the request must declare {missing}; the branch is bound at phase one and no later "
            "step may choose it",
        )
    if request.config is not None:
        problem = checkout_problem(request.config, workdir=request.workdir)
        if problem is not None:
            return Outcome(Status.BLOCKED_GITHUB_ACCESS, problem)
    return None


def _resolve_target(request: RunRequest) -> tuple[BoundTarget | None, Outcome | None]:
    """Freeze where this run pushes and what it is measured against. Runs under the lock.

    The base is read from the **remote**, not from whatever `origin/main` happens to point at in
    a container whose refs may be days old, and it is stored as a full SHA. Everything after
    this reads it from the token: a `--base` chosen at postflight time is a caller deciding how
    much of its own work to submit for inspection, which on a resumed branch means `HEAD~1`
    hides every commit but the last. Which remote and which base branch are not the request's
    to choose either — those come from the committed production target.
    """
    spec = _effective_target(request)
    remote, branch = spec["remote"], spec["branch"]
    base_branch = spec["base_branch"]
    workdir = Path(spec.get("workdir") or request.workdir)
    expected = f"{_branch_prefix(request)}{request.work_id}"
    if not branch.startswith(expected):
        # Checked here, after the queue has confirmed the work id against the issue, so that a
        # run pointed at the wrong issue reports the mismatch rather than the branch name.
        return None, Outcome(
            Status.INVALID_SPEC,
            f"branch {branch!r} does not begin with {expected!r}, so it does not belong to this "
            "work item",
        )
    try:
        base_sha = remote_head(remote, base_branch, workdir=workdir)
    except LockUnavailable as error:
        return None, Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))
    if base_sha is None:
        return None, Outcome(Status.BLOCKED_GITHUB_ACCESS, f"{remote} has no branch {base_branch}")
    target = BoundTarget(
        remote=remote,
        branch=branch,
        base_branch=base_branch,
        base_sha=base_sha,
        workdir=str(workdir),
        repository=spec.get("repository") or "",
    )
    problem = target.problem()
    if problem is not None:
        return None, Outcome(Status.INVALID_SPEC, f"the target {problem}")
    if not _commit_present(workdir, base_sha):
        return None, Outcome(
            Status.BLOCKED_ENVIRONMENT,
            f"{base_branch} is at {base_sha[:12]} on {remote}, which this checkout does not "
            "have; fetch the base before starting, or the diff would be measured from nothing",
        )
    return target, None


def _hand_back(store: LockStore, work_id: str, owner: str, refusal: Outcome) -> Outcome:
    """Refuse, give the lock back, and say so when the release itself did not work.

    A release failure used to be dropped on this path: the refusal was reported and the lock
    stayed on the remote with nothing recording that it had. Every later run would then report
    `ALREADY_RUNNING` for a run that ended minutes ago.
    """
    ref = store.ref(work_id) if hasattr(store, "ref") else work_id
    sha = store.token_for(work_id) or ""
    # Never a delete: this environment refuses those, and a recovery step that cannot run is
    # worse than none. The runbook's tombstone procedure is the one way back.
    recovery = (
        f"recover with the tombstone procedure in docs/operations/routine_runbook.md for "
        f"{ref} at {sha[:12] or 'its current SHA'}"
    )
    try:
        released = store.release(work_id, owner)
    except LockUnavailable as error:
        return Outcome(
            refusal.status,
            f"{refusal.detail}; AND the lock could not be released: {error}. {recovery}",
            {**refusal.evidence, "lock_released": "no", "lock_ref": ref},
        )
    if not released:
        return Outcome(
            refusal.status,
            f"{refusal.detail}; AND the release was refused, so the lock may be stuck. {recovery}",
            {**refusal.evidence, "lock_released": "no", "lock_ref": ref},
        )
    return refusal.with_evidence(lock_released="yes")


def command_preflight(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args)
    if failure is not None:
        return failure
    assert request is not None

    failure = _target_shape(request)
    if failure is not None:
        return failure

    try:
        approvers = load_approvers(_repo_root() / APPROVERS_PATH)
        revisions, refused = request.revisions(approvers)
        applied = request.applied_revision_ids()
        pull_requests = request.pull_requests()
        recorder = request.state_store()
    except (ApproverConfigError, StateCorrupt, RequestSchemaError) as error:
        return Outcome(Status.INVALID_SPEC, str(error))
    except (LockUnavailable, SchemaError) as error:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error))

    if revisions and recorder is None:
        # Found here rather than at finalize, which is after the push: a run that carries out an
        # approved revision with nowhere to record it will carry the same one out again tomorrow.
        return Outcome(
            Status.INVALID_SPEC,
            f"{len(revisions)} approved revision instruction(s) are in play but the request "
            "configures no durable state store, so nothing would remember they were applied",
        )

    store, failure = _store(request)
    if failure is not None:
        return failure
    assert store is not None

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

    target, failure = _resolve_target(request)
    if failure is not None:
        # The lock was taken a few lines ago and this run is over; holding it would block the
        # next one for a reason that has already ended — and a release that fails is reported
        # rather than swallowed.
        return _hand_back(store, request.work_id, owner, failure)
    assert target is not None

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
        target=target,
    )
    token.write(args.token)
    return Outcome(
        Status.READY_TO_IMPLEMENT,
        f"lock held for {request.work_id}; now re-read GitHub and run `confirm`",
        {
            **outcome.evidence,
            "token": str(args.token),
            "phase": "1 of 2",
            "branch": target.branch,
            "base": f"{target.base_branch}@{target.base_sha[:12]}",
        },
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
    request, failure = _load(args)
    if failure is not None:
        return failure
    assert request is not None

    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store, failure = _store(request)
    if failure is not None:
        return failure
    assert store is not None

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


def _bound_target(
    request: RunRequest, token: LockToken
) -> tuple[BoundTarget | None, Outcome | None]:
    """The target phase one froze, refusing a request that now describes a different one."""
    target = token.target
    if target is None:
        return None, Outcome(
            Status.INVALID_SPEC,
            "this token carries no bound target; it was minted before the branch and base were "
            "bound, and there is no way to tell what this run was measured against",
        )
    problem = target.problem()
    if problem is not None:
        return None, Outcome(Status.INVALID_SPEC, f"the bound target {problem}")
    declared = request.declared_target()
    for field_name, bound in (
        ("remote", target.remote),
        ("branch", target.branch),
        ("base_branch", target.base_branch),
        ("repository", target.repository),
    ):
        stated = declared.get(field_name)
        if stated and stated != bound:
            return None, Outcome(
                Status.BLOCKED_SCOPE,
                f"the request names {field_name} {stated!r}, but this run is bound to "
                f"{bound or 'none'}; the target is decided at phase one",
            )
    return target, None


def command_postflight(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args)
    if failure is not None:
        return failure
    assert request is not None

    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store, failure = _store(request)
    if failure is not None:
        return failure
    assert store is not None

    lost = _still_ours(store, token)
    if lost is not None:
        return lost

    confirmation, failure = _confirmed(args, token)
    if failure is not None:
        return failure
    assert confirmation is not None

    target, failure = _bound_target(request, token)
    if failure is not None:
        return _abandon(store, token, failure, args.token, args.confirmation)
    assert target is not None

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

    workdir = Path(target.workdir)
    if args.base:
        # The flag survives only so that disagreeing with the token is an error rather than a
        # silent narrowing. `--base HEAD~1` on a branch with four commits inspects one of them.
        given = _rev(workdir, args.base)
        if given != target.base_sha:
            return _abandon(
                store,
                token,
                Outcome(
                    Status.BLOCKED_SCOPE,
                    f"--base {args.base} resolves to {given or 'nothing'} but this run is bound "
                    f"to {target.base_branch} at {target.base_sha[:12]}; the whole change is "
                    "measured from there or not at all",
                ),
                args.token,
                args.confirmation,
            )

    outcome = run_postflight(
        PostflightInputs(
            work_id=token.work_id,
            issue_body=body,
            base=target.base_sha,
            workdir=workdir,
            unchanged=tuple(args.unchanged),
        )
    )
    if not outcome.proceeds:
        return _abandon(store, token, outcome, args.token, args.confirmation)

    head = _rev(workdir, "HEAD")
    Confirmation(**{**confirmation.__dict__, "verified_head": head or ""}).write(args.confirmation)
    return outcome.with_evidence(
        verified_head=head or "unknown",
        base=f"{target.base_branch}@{target.base_sha[:12]}",
        next_step=f"push to {target.remote} {target.branch}, then finalize",
    )


def _rev(workdir: Path, ref: str) -> str | None:
    proc = subprocess.run(["git", "rev-parse", ref], cwd=workdir, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _completion(
    args: argparse.Namespace, token: LockToken, target: BoundTarget, confirmation: Confirmation
) -> Outcome:
    """Read the re-queried pull request payload and judge the deliverable against the token."""
    try:
        raw = json.loads(args.completion.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return Outcome(
            Status.BLOCKED_GITHUB_ACCESS,
            f"no usable completion evidence ({error}); finalize needs the pull request listing "
            "queried after the push",
        )
    if not isinstance(raw, dict):
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, "the completion evidence is not an object")

    captured = str(raw.get("captured_at") or "")
    if not captured or not token.captured_after(captured):
        return Outcome(
            Status.BLOCKED_GITHUB_ACCESS,
            "the completion evidence does not assert that it was captured after the lock was "
            "taken, so it may predate the pull request it is supposed to prove",
        )
    try:
        pulls = read_open_pull_requests(raw.get("pull_requests") or [])
    except SchemaError as error:
        return Outcome(
            Status.BLOCKED_GITHUB_ACCESS, f"the pull request listing did not parse: {error}"
        )

    return check_completion(
        CompletionInputs(
            work_id=token.work_id,
            branch=target.branch,
            base_branch=target.base_branch,
            verified_head=confirmation.verified_head,
            pull_requests=pulls,
            revision_pull_request=token.revision.pull_request if token.revision else None,
        )
    )


def command_finalize(args: argparse.Namespace) -> Outcome:
    """After the push: ask the *remote* what the branch carries, then record and release.

    The previous version compared `--pushed-sha` — a string the caller produced, in practice
    from its own `git rev-parse HEAD` — against the verified head. That answers "does this
    commit exist locally", which is equally true when the push failed, when it went to another
    branch, and when it never ran. So the authority here is `git ls-remote`, and `--pushed-sha`
    survives only as a claim the remote is allowed to contradict.
    """
    request, failure = _load(args)
    if failure is not None:
        return failure
    assert request is not None

    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store, failure = _store(request)
    if failure is not None:
        return failure
    assert store is not None

    lost = _still_ours(store, token)
    if lost is not None:
        return lost

    confirmation, failure = _confirmed(args, token)
    if failure is not None:
        return failure
    assert confirmation is not None

    target, failure = _bound_target(request, token)
    if failure is not None:
        return failure
    assert target is not None

    if not confirmation.verified_head:
        return Outcome(
            Status.BLOCKED_SCOPE,
            "postflight has not verified a commit for this run; there is nothing to finalize",
        )

    try:
        landed = remote_head(target.remote, target.branch, workdir=Path(target.workdir))
    except LockUnavailable as error:
        # Nothing is cleaned up: the run is unfinished, not finished badly.
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, f"cannot read the pushed branch: {error}")

    if landed is None:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"{target.remote} has no branch {target.branch}: verification passed on "
            f"{confirmation.verified_head[:12]} but nothing was pushed",
            {"branch": target.branch, "verified_head": confirmation.verified_head},
        )
    if landed != confirmation.verified_head:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"{target.branch} carries {landed[:12]} but verification passed on "
            f"{confirmation.verified_head[:12]}; the commit on the remote was never checked",
            {"remote_head": landed, "verified_head": confirmation.verified_head},
        )
    if args.pushed_sha and args.pushed_sha != landed:
        return Outcome(
            Status.BLOCKED_SCOPE,
            f"the caller reports pushing {args.pushed_sha[:12]}, but {target.remote} "
            f"{target.branch} carries {landed[:12]}",
            {"remote_head": landed, "claimed": args.pushed_sha},
        )

    # The branch is only half the deliverable. The Routine's output is a draft pull request, and
    # a run that pushed a branch nobody was asked to look at has not finished.
    deliverable = _completion(args, token, target, confirmation)
    if not deliverable.proceeds:
        return deliverable

    if token.revision is not None:
        recorder = request.state_store()
        if recorder is None:
            return Outcome(
                Status.BLOCKED_GITHUB_ACCESS,
                f"revision {token.revision.record_id} was applied and pushed but there is no "
                "durable store to record it in; the next run would apply it again",
            )
        try:
            # Idempotent, which is what makes a second finalize after a failed release safe.
            recorder.record(token.revision.record_id)
        except (LockUnavailable, StateCorrupt) as error:
            return Outcome(
                Status.BLOCKED_GITHUB_ACCESS,
                f"could not record revision {token.revision.record_id}: {error}",
            )

    evidence = {
        "recorded_revision": token.revision.record_id if token.revision else "none",
        "remote_head": landed,
        "branch": target.branch,
        **deliverable.evidence,
    }
    try:
        released = _release(store, token)
    except LockUnavailable as error:
        released = False
        why = str(error)
    else:
        why = "the remote refused the delete, or the lock is no longer ours"

    if not released:
        # Exit 0 here used to mean "finished" while the lock stayed held, so every later run
        # reported ALREADY_RUNNING and the artifacts needed to release it had been deleted.
        return Outcome(
            Status.BLOCKED_GITHUB_ACCESS,
            f"{landed[:12]} is on {target.branch} and the work is recorded, but the lock on "
            f"{token.work_id} could not be released: {why}. The token and confirmation are "
            f"kept so `release --token {args.token}` can retry; if it keeps failing, follow the "
            f"tombstone procedure in docs/operations/routine_runbook.md for {token.lock_ref} at "
            f"{token.lock_sha[:12]} — never a ref delete, which this environment refuses",
            {**evidence, "lock_released": "no", "token": str(args.token)},
        )

    args.token.unlink(missing_ok=True)
    args.confirmation.unlink(missing_ok=True)
    return Outcome(
        Status.READY_TO_IMPLEMENT,
        f"{deliverable.detail}; work item {token.work_id} complete",
        {**evidence, "lock_released": "yes"},
    )


def command_release(args: argparse.Namespace) -> Outcome:
    request, failure = _load(args)
    if failure is not None:
        return failure
    assert request is not None
    token, failure = _read_token(args.token)
    if failure is not None:
        return failure
    assert token is not None

    store, failure = _store(request)
    if failure is not None:
        return failure
    assert store is not None

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
        step.add_argument(
            "--development",
            action="store_true",
            help="tests only: permit file and memory lock stores, which one container can see",
        )
        if name in {"confirm", "postflight", "finalize"}:
            step.add_argument("--confirmation", required=True, type=Path)
        if name == "confirm":
            step.add_argument("--proceed-marker", type=Path)
        if name == "postflight":
            # Not required, and not authoritative: the base is the token's. Passing one that
            # disagrees is refused rather than obeyed.
            step.add_argument("--base", default="")
            step.add_argument("--unchanged", action="append", default=[])
        if name == "finalize":
            # A claim about what was pushed. `git ls-remote` decides; this only has to agree.
            step.add_argument("--pushed-sha", default="")
            step.add_argument("--completion", required=True, type=Path)

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
    except LockCorrupt as error:
        # Fail-closed, and deliberately not ALREADY_RUNNING: a lock nobody can parse is not a
        # lock somebody holds, and it is not a free one either.
        outcome = Outcome(Status.INVALID_SPEC, f"the lock ref is unusable: {error}")

    print(report(outcome, as_json=args.json))
    return outcome.exit_code
