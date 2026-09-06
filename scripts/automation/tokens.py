"""The chain of custody: what each step must present to prove it is the run before it.

Four commands, four processes, four chances for the state one of them decided about to be
replaced before the next one acts on it. The pieces here are what stop that.

**The token** is written by `preflight` and carries the whole decision, not just the lock: the
issue it chose, a hash of the exact body it validated, the pull requests it saw, and — bound,
not passed along later — the revision instruction it selected. Anything a later step needs to
know about phase one comes from here rather than from a file the agent can edit in between.

**The confirmation artifact** is written by `confirm` and is what `postflight` demands. Without
it, `preflight → postflight` skips the re-read entirely, which was possible until now: the token
alone was enough.

**Neither is a substitute for asking the remote.** Both are local files. They prove what a run
once decided; they prove nothing about whether it still holds the lock. Every step re-reads the
lock ref and compares it to `lock_sha` before doing anything, because another run can delete the
ref and take it while a perfectly valid-looking token sits on disk.

`captured_at` deserves its own warning, and the docs carry it too: it is a string the agent
writes. It is **an agent-provided freshness assertion, not evidence**. What is checked here is
weaker and honest — that the phase-two file did not exist before the lock was taken, which at
least rules out a file prepared in advance.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BoundRevision:
    """The revision instruction phase one selected, pinned so no later step can swap it."""

    record_id: str
    pull_request: int
    head_sha: str
    body_sha: str

    @classmethod
    def of(cls, instruction) -> BoundRevision:
        return cls(
            record_id=instruction.approval_record_id,
            pull_request=instruction.target_pull_request,
            head_sha=instruction.target_head_sha,
            body_sha=sha256_of(instruction.content),
        )

    def matches(self, instruction) -> bool:
        return (
            self.record_id == instruction.approval_record_id
            and self.pull_request == instruction.target_pull_request
            and self.head_sha == instruction.target_head_sha
            and self.body_sha == sha256_of(instruction.content)
        )


@dataclass(frozen=True)
class LockToken:
    """Proof of holding one work item's lock, plus the decision that lock protects."""

    work_id: str
    owner: str
    #: What the lock store holds. Every later step compares the *remote* against this.
    lock_sha: str
    lock_ref: str
    acquired_at: str
    issue_number: int
    #: Hash of the exact issue body phase one validated. postflight's path policy comes from a
    #: body matching this, never from whatever the request file happens to say now.
    issue_body_sha: str
    fingerprint: str
    secret: str
    pull_requests: tuple[str, ...] = ()
    existing_branches: tuple[str, ...] = ()
    revision: BoundRevision | None = None

    @classmethod
    def mint(
        cls,
        *,
        work_id: str,
        owner: str,
        lock_sha: str,
        lock_ref: str,
        issue_number: int,
        issue_body: str,
        fingerprint: str,
        pull_requests: tuple[str, ...] = (),
        existing_branches: tuple[str, ...] = (),
        revision: BoundRevision | None = None,
    ) -> LockToken:
        return cls(
            work_id=work_id,
            owner=owner,
            lock_sha=lock_sha,
            lock_ref=lock_ref,
            acquired_at=_now(),
            issue_number=issue_number,
            issue_body_sha=sha256_of(issue_body),
            fingerprint=fingerprint,
            secret=secrets.token_hex(16),
            pull_requests=pull_requests,
            existing_branches=existing_branches,
            revision=revision,
        )

    @property
    def identity(self) -> str:
        """A hash of the secret. Safe to put in an artifact the agent can read."""
        return sha256_of(self.secret)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> LockToken:
        raw = json.loads(path.read_text(encoding="utf-8"))
        missing = {f for f in cls.__dataclass_fields__ if f not in raw}
        if missing:
            raise ValueError(f"lock token is missing {', '.join(sorted(missing))}")
        revision = raw.get("revision")
        return cls(
            **{
                key: raw[key]
                for key in cls.__dataclass_fields__
                if key not in {"revision", "pull_requests", "existing_branches"}
            },
            pull_requests=tuple(raw.get("pull_requests") or ()),
            existing_branches=tuple(raw.get("existing_branches") or ()),
            revision=BoundRevision(**revision) if revision else None,
        )

    def captured_after(self, captured_at: str) -> bool:
        """Whether a timestamp claims to postdate the lock. An assertion, not evidence."""
        try:
            when = datetime.fromisoformat(captured_at)
        except ValueError:
            return False
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when >= datetime.fromisoformat(self.acquired_at)

    def acquired_epoch(self) -> float:
        return datetime.fromisoformat(self.acquired_at).timestamp()


@dataclass(frozen=True)
class Confirmation:
    """Written only by a successful `confirm`. `postflight` refuses to run without it."""

    token_identity: str
    work_id: str
    issue_number: int
    fingerprint: str
    #: The body `confirm` actually re-read and matched. postflight's policy comes from this.
    confirmed_issue_body_sha: str
    confirmed_at: str
    pull_request: int | None = None
    pull_request_head_sha: str = ""
    revision_record_id: str = ""
    #: Set by postflight, read by finalize: the commit the verification actually passed on.
    verified_head: str = ""
    evidence: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        token: LockToken,
        *,
        issue_body: str,
        pull_request: int | None = None,
        pull_request_head_sha: str = "",
    ) -> Confirmation:
        return cls(
            token_identity=token.identity,
            work_id=token.work_id,
            issue_number=token.issue_number,
            fingerprint=token.fingerprint,
            confirmed_issue_body_sha=sha256_of(issue_body),
            confirmed_at=_now(),
            pull_request=pull_request,
            pull_request_head_sha=pull_request_head_sha,
            revision_record_id=token.revision.record_id if token.revision else "",
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> Confirmation:
        raw = json.loads(path.read_text(encoding="utf-8"))
        missing = {
            name
            for name, spec in cls.__dataclass_fields__.items()
            if name not in raw and spec.default is spec.default_factory is not None
        }
        if "token_identity" not in raw:
            raise ValueError("confirmation is missing token_identity")
        if missing:
            raise ValueError(f"confirmation is missing {', '.join(sorted(missing))}")
        return cls(**{key: raw[key] for key in cls.__dataclass_fields__ if key in raw})

    def problem_against(self, token: LockToken) -> str | None:
        """Why this confirmation does not belong to this token, or None when it does."""
        if self.token_identity != token.identity:
            return "the confirmation belongs to a different run"
        if self.work_id != token.work_id:
            return f"the confirmation is for {self.work_id!r}, the lock for {token.work_id!r}"
        if self.issue_number != token.issue_number:
            return (
                f"the confirmation names issue #{self.issue_number}, the lock #{token.issue_number}"
            )
        if self.fingerprint != token.fingerprint:
            return "the confirmation was made against a different phase-one decision"
        if self.confirmed_issue_body_sha != token.issue_body_sha:
            return "the confirmed issue body is not the one phase one validated"
        expected = token.revision.record_id if token.revision else ""
        if self.revision_record_id != expected:
            return (
                f"the confirmation carries revision {self.revision_record_id!r} but the lock "
                f"binds {expected!r}"
            )
        return None


def fingerprint_of(*, issue_number: int, issue_body: str, pull_requests: tuple) -> str:
    """A stable summary of the world phase one acted on.

    Deliberately coarse: the issue it chose, the contract it validated, and every open pull
    request with its head. If any of those move between the phases, the decision phase one made
    was about a situation that no longer exists.
    """
    parts = [str(issue_number), issue_body]
    ordered = sorted(pull_requests, key=lambda pr: pr.number)
    parts.extend(f"{pr.number}:{pr.head_sha}" for pr in ordered)
    return sha256_of("\x1f".join(parts))
