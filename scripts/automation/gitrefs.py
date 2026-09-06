"""A lock and a memory that outlive the container, built on the one thing every run shares.

`FileLockStore` is atomic and useless here: scheduled runs get one container each, so two of
them hold two empty lock directories and neither can see the other. The only store both runs
can reach is the git remote, and git already offers exactly the primitive a lock needs.

**Creating a ref is a compare-and-swap.** A push that would not fast-forward an existing ref is
rejected by the server, and the commit this store pushes is an *orphan* - no parents, unique
content per run - so it can never be an ancestor of whatever is already there. While the ref
exists, every other run's push is rejected. Exactly one creation wins, decided by the remote,
not by either contender's belief about the other.

Three distinctions this module refuses to blur:

* **rejected is not failed.** A rejected push means somebody else holds the lock and this run
  should stop politely. A push that failed for any other reason - auth, network, an unreachable
  remote - is an infrastructure problem, and treating it as "lock acquired" would be the worst
  possible reading. It raises :class:`LockUnavailable`, which the gate reports as
  ``BLOCKED_GITHUB_ACCESS``.
* **holding is not owning.** ``release`` refuses to delete a lock this run did not take, and
  does it with ``--force-with-lease`` so the delete itself is a compare-and-swap rather than a
  read followed by a hopeful write.
* **state is not session memory.** Applied revision ids live in a ref too, so a restarted run
  reads what its predecessor did instead of doing it again.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
#: git's own words for "somebody got there first".
_CONTENTION = ("non-fast-forward", "fetch first", "rejected", "cannot lock ref", "stale info")

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "vcrp-automation",
    "GIT_AUTHOR_EMAIL": "automation@vcrp.invalid",
    "GIT_COMMITTER_NAME": "vcrp-automation",
    "GIT_COMMITTER_EMAIL": "automation@vcrp.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


class LockUnavailable(RuntimeError):
    """The lock could not be reached. Never raised merely because someone else holds it."""


def _safe(key: str) -> str:
    return _UNSAFE.sub("_", key)


@dataclass
class GitRefLockStore:
    """A cross-container lock whose atomicity is the git remote's, not this process's."""

    remote: str
    workdir: Path
    namespace: str = "refs/vcrp-locks"
    _held: dict[str, str] = field(default_factory=dict, repr=False)

    def _git(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        import os

        return subprocess.run(
            ["git", *args],
            cwd=self.workdir,
            capture_output=True,
            text=True,
            input=stdin,
            env={**os.environ, **_GIT_ENV},
        )

    def _ref(self, key: str) -> str:
        return f"{self.namespace}/{_safe(key)}"

    def _mint(self, key: str, owner: str) -> str:
        """An orphan commit unique to this run. Uniqueness is what makes the push a CAS."""
        tree = self._git("mktree", stdin="")
        if tree.returncode != 0:
            raise LockUnavailable(f"cannot build a lock object: {tree.stderr.strip()}")
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        message = f"lock {key}\nowner: {owner}\ntaken: {stamp}\n"
        commit = self._git("commit-tree", tree.stdout.strip(), stdin=message)
        if commit.returncode != 0:
            raise LockUnavailable(f"cannot build a lock commit: {commit.stderr.strip()}")
        return commit.stdout.strip()

    def create_exclusive(self, key: str, owner: str) -> bool:
        """True only for the run whose push created the ref. Contention returns False."""
        sha = self._mint(key, owner)
        pushed = self._git("push", self.remote, f"{sha}:{self._ref(key)}")
        if pushed.returncode == 0:
            self._held[key] = sha
            return True
        combined = (pushed.stderr + pushed.stdout).lower()
        if any(word in combined for word in _CONTENTION):
            return False
        raise LockUnavailable(
            f"the lock remote could not be reached: {(pushed.stderr or pushed.stdout).strip()}"
        )

    def holder(self, key: str) -> str:
        fetched = self._git("fetch", self.remote, f"+{self._ref(key)}:refs/vcrp-peek")
        if fetched.returncode != 0:
            return ""
        shown = self._git("log", "-1", "--format=%B", "refs/vcrp-peek")
        self._git("update-ref", "-d", "refs/vcrp-peek")
        return shown.stdout.strip() if shown.returncode == 0 else ""

    def release(self, key: str, owner: str = "") -> bool:
        """Delete the lock, but only the one this run took. Returns False when it is not ours."""
        sha = self._held.get(key)
        if sha is None:
            return False
        deleted = self._git(
            "push", f"--force-with-lease={self._ref(key)}:{sha}", self.remote, f":{self._ref(key)}"
        )
        if deleted.returncode == 0:
            self._held.pop(key, None)
            return True
        return False


@dataclass
class GitRefStateStore:
    """Small durable facts - which revision instructions have been carried out - in a ref."""

    remote: str
    workdir: Path
    ref: str = "refs/vcrp-state/applied-revisions"

    def _git(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        import os

        return subprocess.run(
            ["git", *args],
            cwd=self.workdir,
            capture_output=True,
            text=True,
            input=stdin,
            env={**os.environ, **_GIT_ENV},
        )

    def load(self) -> frozenset[str]:
        fetched = self._git("fetch", self.remote, f"+{self.ref}:refs/vcrp-state-peek")
        if fetched.returncode != 0:
            return frozenset()
        shown = self._git("show", "refs/vcrp-state-peek:applied.json")
        self._git("update-ref", "-d", "refs/vcrp-state-peek")
        if shown.returncode != 0:
            return frozenset()
        try:
            return frozenset(json.loads(shown.stdout))
        except json.JSONDecodeError:
            return frozenset()

    def record(self, identifier: str) -> frozenset[str]:
        """Add one id and publish it. Read-modify-write, so a lost race is retried by the caller."""
        current = set(self.load())
        current.add(identifier)
        payload = json.dumps(sorted(current), indent=2) + "\n"

        blob = self._git("hash-object", "-w", "--stdin", stdin=payload)
        if blob.returncode != 0:
            raise LockUnavailable(f"cannot write state: {blob.stderr.strip()}")
        tree = self._git("mktree", stdin=f"100644 blob {blob.stdout.strip()}\tapplied.json\n")
        if tree.returncode != 0:
            raise LockUnavailable(f"cannot build state tree: {tree.stderr.strip()}")
        commit = self._git("commit-tree", tree.stdout.strip(), stdin="applied revisions\n")
        if commit.returncode != 0:
            raise LockUnavailable(f"cannot build state commit: {commit.stderr.strip()}")

        pushed = self._git("push", "--force", self.remote, f"{commit.stdout.strip()}:{self.ref}")
        if pushed.returncode != 0:
            raise LockUnavailable(f"cannot publish state: {pushed.stderr.strip()}")
        return frozenset(current)
