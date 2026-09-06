"""One run at a time, decided by an atomic primitive rather than by an instruction.

A prompt that says "stop if another run is going" is not a lock. It is a request delivered to
the only party that cannot check whether the other party received it, and two runs that both
read the same instruction both conclude they are the only one. So a store exposes exactly one
operation - create this key, and tell me whether **I** created it - and the answer comes from
the filesystem or a remote, never from the caller's own memory.

Two implementations, with different reach, and the difference is not a detail:

* :class:`FileLockStore` uses ``O_CREAT | O_EXCL``, one syscall the kernel resolves for all
  contenders. It is atomic within **one filesystem**, which makes it right for two processes in
  one container and blind to a run in another.
* :class:`~automation.gitrefs.GitRefLockStore` pushes an orphan commit to a ref, and the remote
  rejects every push but the first. That one reaches across containers, which is where
  scheduled runs actually live.

Releasing checks ownership in both. A run that did not take the lock cannot drop it, because
the failure that makes a stuck lock dangerous - a crashed run - is also the one where some
other run would love to clear it and start.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .gitrefs import LockUnavailable
from .outcomes import Outcome, Status

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class LockStore(Protocol):
    """Somewhere a lock can be created atomically and seen by every contender."""

    def create_exclusive(self, key: str, owner: str) -> bool:
        """True only for the caller that created the key. False on contention.

        Raises :class:`~automation.gitrefs.LockUnavailable` when the store itself could not be
        reached - which is never the same thing as the lock being free.
        """

    def holder(self, key: str) -> str:
        """Whoever holds the key, or an empty string."""

    def release(self, key: str, owner: str = "") -> bool:
        """Drop the key if this caller holds it. False when it belongs to someone else."""


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

    def release(self, key: str, owner: str = "") -> bool:
        held = self._held.get(key)
        if held is None or (owner and held != owner):
            return False
        del self._held[key]
        return True


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
        except OSError as error:  # a directory that vanished, a full disk - not a free lock
            raise LockUnavailable(f"cannot reach the lock directory: {error}") from error
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{owner} {stamp}\n")
        return True

    def holder(self, key: str) -> str:
        path = self._path(key)
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def release(self, key: str, owner: str = "") -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        if owner and not path.read_text(encoding="utf-8").startswith(owner):
            return False
        path.unlink(missing_ok=True)
        return True


def acquire(store: LockStore, key: str, *, owner: str) -> Outcome:
    """Take the lock, or report who has it. Contention is an outcome; unreachable is a block."""
    try:
        taken = store.create_exclusive(key, owner)
    except LockUnavailable as error:
        return Outcome(Status.BLOCKED_GITHUB_ACCESS, str(error), {"lock": key})
    if taken:
        return Outcome(Status.READY_TO_IMPLEMENT, f"holding the lock for {key}", {"lock": key})
    return Outcome(
        Status.ALREADY_RUNNING,
        f"{key} is already held by {store.holder(key) or 'another run'}",
        {"lock": key},
    )
