"""A lock and a memory that outlive the container, built on the one thing every run shares.

`FileLockStore` is atomic and useless here: scheduled runs get one container each, so two of
them hold two empty lock directories and neither can see the other. The only store both runs
can reach is the git remote, and git already offers exactly the primitive a lock needs.

**Creating a ref is a compare-and-swap.** A push that would not fast-forward an existing ref is
rejected by the server, so while the ref exists every other run's push is rejected. Exactly one
creation wins, decided by the remote, not by either contender's belief about the other.

That argument has one hole, and it was live in the first version of this file: it assumes the
two contenders build *different* commits. Git objects are content-addressed, so two runs with
the same work id, the same owner and the same one-second timestamp built **the same commit**,
and the second push found the ref already pointing at that exact object. Git calls that
"Everything up-to-date", exits 0, and both runs concluded they held the lock:

    same-owner same-second lock results: [True, True]

So every lock commit now carries a 32-hex-character nonce from :mod:`secrets`, which no other
run will reproduce, and an up-to-date push is treated as contention rather than success. The
uniqueness is the lock; the CAS only enforces it.

Three distinctions this module refuses to blur:

* **rejected is not failed.** A rejected push means somebody else holds the lock and this run
  should stop politely. A push that failed for any other reason - auth, network, an unreachable
  remote - raises :class:`LockUnavailable`, which the gate reports as ``BLOCKED_GITHUB_ACCESS``.
  Treating an unreachable remote as a free lock would be the worst available reading.
* **holding is not owning.** ``release`` refuses to drop a lock this run did not take, and does
  it with ``--force-with-lease`` so the delete is itself a compare-and-swap. The token survives
  the process (:mod:`automation.tokens`), so a later invocation can still release it.
* **absent is not unreadable.** A state ref that does not exist yet is an empty set. A state ref
  that could not be *reached* is a blocked run — reading "no revisions have been applied" out of
  a failed fetch is how an approved revision gets applied twice.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
#: git's own words for "somebody got there first".
_CONTENTION = ("non-fast-forward", "fetch first", "rejected", "cannot lock ref", "stale info")
#: git's words for "your object is already what the ref points at" — which, for a lock, means
#: the ref was not created by this push.
_ALREADY_THERE = ("everything up-to-date", "up to date")

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "vcrp-automation",
    "GIT_AUTHOR_EMAIL": "automation@vcrp.invalid",
    "GIT_COMMITTER_NAME": "vcrp-automation",
    "GIT_COMMITTER_EMAIL": "automation@vcrp.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


class LockUnavailable(RuntimeError):
    """The store could not be reached. Never raised merely because someone else holds it."""


class StateCorrupt(RuntimeError):
    """The durable state exists but cannot be trusted. Distinct from unreachable, and fatal."""


def _safe(key: str) -> str:
    return _UNSAFE.sub("_", key)


def _git(workdir: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        input=stdin,
        env={**os.environ, **_GIT_ENV},
    )


@dataclass
class GitRefLockStore:
    """A cross-container lock whose atomicity is the git remote's, not this process's."""

    remote: str
    workdir: Path
    namespace: str = "refs/vcrp-locks"
    #: Unique to this store instance, and therefore to this run. This is what makes the lock
    #: commit unforgeably distinct from every other contender's.
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))
    _held: dict[str, str] = field(default_factory=dict, repr=False)

    def ref(self, key: str) -> str:
        return f"{self.namespace}/{_safe(key)}"

    def token_for(self, key: str) -> str | None:
        """The commit this run pushed, which is what proves ownership later."""
        return self._held.get(key)

    def held_token(self, key: str) -> str | None:
        """What the *remote* currently holds, or None when the ref is genuinely absent.

        This is the question every later step has to ask. A token file on disk proves what this
        run once took; it proves nothing about now. Another run can delete the ref and take it,
        and the stale token would still look convincing.
        """
        listed = _git(self.workdir, "ls-remote", "--exit-code", self.remote, self.ref(key))
        if listed.returncode == 0:
            return listed.stdout.split()[0]
        if listed.returncode == 2:
            return None
        raise LockUnavailable(
            f"cannot read the lock ref: {(listed.stderr or listed.stdout).strip()}"
        )

    def _mint(self, key: str, owner: str) -> str:
        tree = _git(self.workdir, "mktree", stdin="")
        if tree.returncode != 0:
            raise LockUnavailable(f"cannot build a lock object: {tree.stderr.strip()}")
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        message = f"lock {key}\nowner: {owner}\ntaken: {stamp}\nnonce: {self.nonce}\n"
        commit = _git(self.workdir, "commit-tree", tree.stdout.strip(), stdin=message)
        if commit.returncode != 0:
            raise LockUnavailable(f"cannot build a lock commit: {commit.stderr.strip()}")
        return commit.stdout.strip()

    def create_exclusive(self, key: str, owner: str) -> bool:
        """True only for the run whose push created the ref. Contention returns False."""
        sha = self._mint(key, owner)
        pushed = _git(self.workdir, "push", self.remote, f"{sha}:{self.ref(key)}")
        combined = (pushed.stderr + pushed.stdout).lower()
        if pushed.returncode == 0:
            if any(word in combined for word in _ALREADY_THERE):
                # The ref already pointed here. Nothing was created, so nothing was won.
                return False
            self._held[key] = sha
            return True
        if any(word in combined for word in _CONTENTION):
            return False
        raise LockUnavailable(
            f"the lock remote could not be reached: {(pushed.stderr or pushed.stdout).strip()}"
        )

    def holder(self, key: str) -> str:
        fetched = _git(self.workdir, "fetch", self.remote, f"+{self.ref(key)}:refs/vcrp-peek")
        if fetched.returncode != 0:
            return ""
        shown = _git(self.workdir, "log", "-1", "--format=%B", "refs/vcrp-peek")
        _git(self.workdir, "update-ref", "-d", "refs/vcrp-peek")
        return shown.stdout.strip() if shown.returncode == 0 else ""

    def release(self, key: str, owner: str = "", *, token: str | None = None) -> bool:
        """Delete the lock, but only the one this run took.

        ``token`` is the lock commit's SHA, which a later process reads from the durable token
        file. Without it this only works inside the process that took the lock, which is how the
        first version stranded its own locks.
        """
        sha = token or self._held.get(key)
        if sha is None:
            return False
        deleted = _git(
            self.workdir,
            "push",
            f"--force-with-lease={self.ref(key)}:{sha}",
            self.remote,
            f":{self.ref(key)}",
        )
        if deleted.returncode == 0:
            self._held.pop(key, None)
            return True
        return False


@dataclass
class GitRefStateStore:
    """Small durable facts - which revision instructions have been carried out - in a ref.

    Fail-closed, because the failure mode is duplicate work: reading an unreachable remote as
    "nothing has been applied" is exactly how an approved revision gets carried out twice.
    """

    remote: str
    workdir: Path
    ref: str = "refs/vcrp-state/applied-revisions"
    retries: int = 3

    def _remote_sha(self) -> str | None:
        """The ref's current value, None when it genuinely does not exist. Raises when unsure."""
        listed = _git(self.workdir, "ls-remote", "--exit-code", self.remote, self.ref)
        if listed.returncode == 0:
            return listed.stdout.split()[0]
        if listed.returncode == 2:  # reached the remote; no such ref
            return None
        raise LockUnavailable(
            f"cannot reach the state remote: {(listed.stderr or listed.stdout).strip()}"
        )

    def load(self) -> frozenset[str]:
        sha = self._remote_sha()
        if sha is None:
            return frozenset()
        fetched = _git(self.workdir, "fetch", self.remote, f"+{self.ref}:refs/vcrp-state-peek")
        if fetched.returncode != 0:
            raise LockUnavailable(f"cannot fetch durable state: {fetched.stderr.strip()}")
        shown = _git(self.workdir, "show", "refs/vcrp-state-peek:applied.json")
        _git(self.workdir, "update-ref", "-d", "refs/vcrp-state-peek")
        if shown.returncode != 0:
            raise StateCorrupt(f"{self.ref} exists but holds no applied.json")
        try:
            loaded = json.loads(shown.stdout)
        except json.JSONDecodeError as error:
            raise StateCorrupt(f"{self.ref} holds malformed JSON: {error}") from error
        if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
            raise StateCorrupt(f"{self.ref} does not hold a list of identifiers")
        return frozenset(loaded)

    def record(self, identifier: str) -> frozenset[str]:
        """Add one id and publish it, as a compare-and-swap that retries on a lost race."""
        last: str = ""
        for _ in range(self.retries):
            before = self._remote_sha()
            current = set(self.load())
            if identifier in current:
                return frozenset(current)
            current.add(identifier)
            commit = self._commit(json.dumps(sorted(current), indent=2) + "\n")

            lease = f"--force-with-lease={self.ref}:{before}" if before else "--force-with-lease"
            pushed = _git(self.workdir, "push", lease, self.remote, f"{commit}:{self.ref}")
            if pushed.returncode == 0:
                return frozenset(current)
            last = (pushed.stderr or pushed.stdout).strip()
        raise LockUnavailable(f"could not publish durable state after {self.retries} tries: {last}")

    def _commit(self, payload: str) -> str:
        blob = _git(self.workdir, "hash-object", "-w", "--stdin", stdin=payload)
        if blob.returncode != 0:
            raise LockUnavailable(f"cannot write state: {blob.stderr.strip()}")
        entry = f"100644 blob {blob.stdout.strip()}\tapplied.json\n"
        tree = _git(self.workdir, "mktree", stdin=entry)
        if tree.returncode != 0:
            raise LockUnavailable(f"cannot build state tree: {tree.stderr.strip()}")
        commit = _git(self.workdir, "commit-tree", tree.stdout.strip(), stdin="applied revisions\n")
        if commit.returncode != 0:
            raise LockUnavailable(f"cannot build state commit: {commit.stderr.strip()}")
        return commit.stdout.strip()
