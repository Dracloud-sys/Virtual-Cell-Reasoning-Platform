"""The lock token: what a later process needs to prove it is the run that took the lock.

Two problems have the same answer.

**The lock outlived the process that took it.** ``create_exclusive`` recorded the lock commit in
an instance attribute, so when the preflight process exited, the only thing that could release
the lock went with it. The first successful run would have stranded its own lock and every
later run would have reported ``ALREADY_RUNNING`` forever.

**"Re-read after locking" was not a re-read.** The first version parsed a second set of GitHub
responses out of the *same* request file that produced the first set — two snapshots taken
before the lock existed, dressed as a before and an after. A real re-read has to happen after
the lock is held, which means it happens in a different process invocation, which means the two
invocations need something to tie them together.

That something is this file. Phase one writes it; phase two must present it, unchanged, along
with responses captured *after* it was written. A confirmation whose evidence predates the lock
is refused, because that is the case the whole two-phase dance exists to exclude.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class LockToken:
    """Proof of holding one work item's lock, durable across processes."""

    work_id: str
    owner: str
    #: The lock commit SHA. `release` uses it as the compare-and-swap expectation.
    lock_sha: str
    lock_ref: str
    acquired_at: str
    issue_number: int
    #: What phase one saw, so phase two can tell whether the world moved underneath it.
    fingerprint: str
    secret: str

    @classmethod
    def mint(
        cls,
        *,
        work_id: str,
        owner: str,
        lock_sha: str,
        lock_ref: str,
        issue_number: int,
        fingerprint: str,
    ) -> LockToken:
        return cls(
            work_id=work_id,
            owner=owner,
            lock_sha=lock_sha,
            lock_ref=lock_ref,
            acquired_at=_now(),
            issue_number=issue_number,
            fingerprint=fingerprint,
            secret=secrets.token_hex(16),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> LockToken:
        raw = json.loads(path.read_text(encoding="utf-8"))
        missing = {f for f in cls.__dataclass_fields__ if f not in raw}
        if missing:
            raise ValueError(f"lock token is missing {', '.join(sorted(missing))}")
        return cls(**{key: raw[key] for key in cls.__dataclass_fields__})

    def matches(self, other: LockToken) -> bool:
        """Constant-ish identity check. A token that differs anywhere is a different run."""
        return (
            self.secret == other.secret
            and self.work_id == other.work_id
            and self.lock_sha == other.lock_sha
        )

    def captured_after(self, captured_at: str) -> bool:
        """Whether evidence with this timestamp was gathered after the lock was taken."""
        try:
            when = datetime.fromisoformat(captured_at)
        except ValueError:
            return False
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when >= datetime.fromisoformat(self.acquired_at)


def fingerprint_of(*, issue_number: int, issue_body: str, pull_requests: tuple) -> str:
    """A stable summary of the world phase one acted on.

    Deliberately coarse: the issue it chose, the contract it validated, and every open pull
    request with its head. If any of those move between the phases, the decision phase one made
    was about a situation that no longer exists.
    """
    import hashlib

    parts = [str(issue_number), issue_body]
    ordered = sorted(pull_requests, key=lambda pr: pr.number)
    parts.extend(f"{pr.number}:{pr.head_sha}" for pr in ordered)
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest
