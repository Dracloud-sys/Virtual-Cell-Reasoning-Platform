"""One run at a time, decided by an atomic primitive rather than by an instruction.

A prompt that says "stop if another run is going" is not a lock. It is a request delivered to
the only party that cannot check whether the other party received it, and two runs that both
read the same instruction both conclude they are the only one. So the store exposes exactly one
operation - create this key, and tell me whether **I** created it - and the answer comes from
the filesystem or a remote, never from the caller's own memory.

``FileLockStore`` is atomic through ``O_CREAT | O_EXCL``, which is a single syscall the kernel
resolves for all contenders. It is also confined to one container: two scheduled runs get two
containers and two empty lock directories, so it cannot see the other run. Closing that needs a
store backed by something both runs share - a remote ref creation, which fails for the loser -
and ``docs/operations/routine_runbook.md`` records that as the gap that gates re-enabling the
schedule.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .outcomes import Outcome, Status

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class LockStore(Protocol):
    """Somewhere a lock can be created atomically and seen by every contender."""

    def create_exclusive(self, key: str, owner: str) -> bool:
        """True only for the caller that created the key. Never raises on contention."""

    def holder(self, key: str) -> str:
        """Whoever holds the key, or an empty string."""

    def release(self, key: str) -> None:
        """Drop the key. Releasing a key nobody holds is not an error."""


class InMemoryLockStore:
    """For tests, and for reasoning about the contract without touching a disk."""

    def __init__(self) -> None:
        self._held: dict[str, str] = {}

    def create_exclusive(self, key: str, owner: str) -> bool:
        if key in self._held:
            return False
        self._held[key] = owner
        return True

    def holder(self, key: str) -> str:
        return self._held.get(key, "")

    def release(self, key: str) -> None:
        self._held.pop(key, None)


class FileLockStore:
    """Exclusive creation on a local filesystem. Atomic within one container, and only there."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # A work id comes from an issue title, so it is untrusted enough to keep inside the
        # directory: every separator and traversal character collapses to a single segment.
        return self._dir / f"{_UNSAFE.sub('_', key)}.lock"

    def create_exclusive(self, key: str, owner: str) -> bool:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            fd = os.open(self._path(key), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{owner} {stamp}\n")
        return True

    def holder(self, key: str) -> str:
        path = self._path(key)
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def release(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def acquire(store: LockStore, key: str, *, owner: str) -> Outcome:
    """Take the lock, or report who already has it. Contention is an outcome, not an error."""
    if store.create_exclusive(key, owner):
        return Outcome(Status.READY_TO_IMPLEMENT, f"holding the lock for {key}", {"lock": key})
    return Outcome(
        Status.ALREADY_RUNNING,
        f"{key} is already held by {store.holder(key) or 'another run'}",
        {"lock": key},
    )
