"""A lock and a memory that outlive the container, built on the one thing every run shares.

`FileLockStore` is atomic and useless here: scheduled runs get one container each, so two of
them hold two empty lock directories and neither can see the other. The only store both runs
can reach is the git remote, and git already offers exactly the primitive a lock needs.

**Updating a ref is a compare-and-swap.** A push that would not fast-forward, or whose lease on
the ref's current value is stale, is rejected by the server. Exactly one contender wins, decided
by the remote rather than by either contender's belief about the other.

Two findings shaped what is here, and both were found by running it against the real remote.

**Deletion is not available.** Releasing used to mean deleting the ref. In the execution
environment this repository's runs actually get, `git push --delete` — with or without a lease —
is refused with HTTP 403, while creating and updating a branch succeeds. A lock that cannot be
released is not a lock: the first run would hold it forever. So a release is now a **state
transition**, not a removal. The ref survives its whole life, moving between `active` and
`tombstone` records, and nothing in the normal or the recovery path ever deletes a ref.

**A push's exit code is not evidence.** That same refused delete printed `Everything
up-to-date` and exited **0**. Reading `returncode == 0` as success would have reported a
released lock that was still held. Every write here is therefore followed by a re-read of the
remote: a write counts only when `ls-remote` shows the SHA this process built, and for a release
only when the object at that SHA parses as a tombstone.

Three distinctions this module refuses to blur:

* **rejected is not failed.** A rejected push means somebody else got there first and this run
  should stop politely. A push that failed for any other reason - auth, network, an unreachable
  remote - raises :class:`LockUnavailable`, which the gate reports as ``BLOCKED_GITHUB_ACCESS``.
  Treating an unreachable remote as a free lock would be the worst available reading.
* **holding is not owning.** A release moves only the exact `active` commit this run took, under
  a lease on that SHA, so an expired generation cannot retire a newer holder's lock.
* **absent is not unreadable.** A state ref that does not exist yet is an empty set. A state ref
  that could not be *reached* is a blocked run — reading "no revisions have been applied" out of
  a failed fetch is how an approved revision gets applied twice. A lock record that does not
  parse is :class:`LockCorrupt`, which is also not a free lock.
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

#: The lock record's format. A reader that does not know this string refuses rather than guesses.
LOCK_SCHEMA = "vcrp-lock/1"
STATE_ACTIVE = "active"
STATE_TOMBSTONE = "tombstone"
#: The file inside the lock commit's tree. Structured, so nothing is decided by substring match.
LOCK_FILE = "lock.json"

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
#: Fields that must be present, a string, and non-empty in every record.
_REQUIRED_STRINGS = ("schema", "work_id", "state", "owner", "nonce", "acquired_at")
#: Fields whose presence depends on the state, but whose *type* never does.
_OPTIONAL_STRINGS = ("released_at", "previous", "release_nonce")

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "vcrp-automation",
    "GIT_AUTHOR_EMAIL": "automation@vcrp.invalid",
    "GIT_COMMITTER_NAME": "vcrp-automation",
    "GIT_COMMITTER_EMAIL": "automation@vcrp.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


class LockUnavailable(RuntimeError):
    """The store could not be reached. Never raised merely because someone else holds it."""


class LockCorrupt(RuntimeError):
    """The lock ref exists but does not parse. Fail-closed: not a free lock, not a held one."""


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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def remote_head(remote: str, branch: str, *, workdir: Path) -> str | None:
    """What the remote says ``refs/heads/<branch>`` points at, or None when it has no such ref.

    This is the question `finalize` exists to ask. The alternative — believing a `--pushed-sha`
    the caller computed from its own `git rev-parse HEAD` — answers "did the local commit
    exist", which is true whether or not the push happened at all.

    Raises :class:`LockUnavailable` when the remote could not be reached: an unreadable remote
    is not an empty one.
    """
    return _remote_sha(remote, f"refs/heads/{branch}", workdir=workdir)


def _remote_sha(remote: str, ref: str, *, workdir: Path) -> str | None:
    """The ref's current value on the remote, None when it genuinely does not exist."""
    listed = _git(workdir, "ls-remote", "--exit-code", remote, ref)
    if listed.returncode == 0:
        return listed.stdout.split()[0]
    if listed.returncode == 2:  # reached the remote; no such ref
        return None
    problem = (listed.stderr or listed.stdout).strip()
    raise LockUnavailable(f"cannot read {ref} on {remote}: {problem}")


@dataclass(frozen=True)
class LockRecord:
    """One state of one work item's lock, as stored in the ref's `lock.json`.

    Everything a later step needs to judge the lock is in here, and it is read by parsing rather
    than by looking for words in a commit message. `generation` is the monotonic identifier: a
    token minted in generation 3 cannot release the lock that generation 4 is holding.
    """

    schema: str
    work_id: str
    state: str
    owner: str
    nonce: str
    generation: int
    acquired_at: str
    released_at: str = ""
    #: The lock commit this record replaced, or "" for the first acquisition.
    previous: str = ""
    #: Set on a tombstone: whose release it was. Without it two processes releasing the same
    #: lock in the same second build byte-identical commits — git is content-addressed, so both
    #: would see "their" commit on the remote and both would report a transition they did not
    #: make. The same collision produced `[True, True]` in an earlier round's acquire path.
    release_nonce: str = ""

    @property
    def active(self) -> bool:
        return self.state == STATE_ACTIVE

    def as_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema": self.schema,
                    "work_id": self.work_id,
                    "state": self.state,
                    "owner": self.owner,
                    "nonce": self.nonce,
                    "generation": self.generation,
                    "acquired_at": self.acquired_at,
                    "released_at": self.released_at,
                    "previous": self.previous,
                    "release_nonce": self.release_nonce,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @classmethod
    def parse(cls, text: str, *, where: str) -> LockRecord:
        """Read a record, or refuse. An unreadable lock is never treated as an absent one.

        Nothing here coerces. An earlier version ran every field through `str(...)` and
        `or ""`, which turned `{"previous": 12345}` and `{"released_at": null}` into
        plausible-looking records — a tombstone with no evidence of a release, accepted as one.
        A value of the wrong type is not a value.
        """
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as error:
            raise LockCorrupt(f"{where} does not hold JSON: {error}") from error
        if not isinstance(raw, dict):
            raise LockCorrupt(f"{where} does not hold an object")

        for name in (*_REQUIRED_STRINGS, *_OPTIONAL_STRINGS):
            if name in raw and not isinstance(raw[name], str):
                kind = type(raw[name]).__name__
                raise LockCorrupt(f"{where} has {name} of type {kind}, which is not a string")
        for name in _REQUIRED_STRINGS:
            if not raw.get(name):
                raise LockCorrupt(f"{where} has no usable {name}")
        if raw["schema"] != LOCK_SCHEMA:
            raise LockCorrupt(f"{where} has schema {raw['schema']!r}, not {LOCK_SCHEMA!r}")
        if raw["state"] not in {STATE_ACTIVE, STATE_TOMBSTONE}:
            raise LockCorrupt(f"{where} has state {raw['state']!r}, which is neither")
        generation = raw.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise LockCorrupt(f"{where} has generation {raw.get('generation')!r}")

        record = cls(
            schema=raw["schema"],
            work_id=raw["work_id"],
            state=raw["state"],
            owner=raw["owner"],
            nonce=raw["nonce"],
            generation=generation,
            acquired_at=raw["acquired_at"],
            released_at=raw.get("released_at", ""),
            previous=raw.get("previous", ""),
            release_nonce=raw.get("release_nonce", ""),
        )
        problem = record._inconsistency()
        if problem is not None:
            raise LockCorrupt(f"{where} {problem}")
        return record

    def _inconsistency(self) -> str | None:
        """Why this record contradicts itself, or None when it holds together.

        A tombstone is the *evidence* that a release happened, so a tombstone missing the marks
        of one — when, by whom, and what it replaced — is not weak evidence. It is a record that
        says a release occurred while carrying nothing that a release produces.
        """
        if self.active:
            if self.released_at:
                return f"is active but carries released_at {self.released_at!r}"
            if self.release_nonce:
                return "is active but carries a release_nonce"
            if self.generation == 1 and self.previous:
                return "is the first generation but names a previous lock commit"
            if self.generation > 1 and not _FULL_SHA.match(self.previous):
                return (
                    f"is generation {self.generation} but its previous {self.previous!r} is not "
                    "a full 40-character commit SHA"
                )
            return None
        if not self.released_at:
            return "is a tombstone that does not say when it was released"
        if not self.release_nonce:
            return "is a tombstone that does not say whose release it was"
        if not _FULL_SHA.match(self.previous):
            return (
                f"is a tombstone whose previous {self.previous!r} is not a full 40-character "
                "commit SHA, so it names no lock to have retired"
            )
        return None

    def describe(self) -> str:
        when = self.released_at if self.state == STATE_TOMBSTONE else self.acquired_at
        return f"{self.owner} ({self.state}, generation {self.generation}, {when})"


@dataclass(frozen=True)
class _PushAttempt:
    """What git said. Kept apart from what the remote holds, which is what actually decides."""

    exited_zero: bool
    contention: bool
    problem: str


@dataclass
class GitRefLockStore:
    """A cross-container lock whose atomicity is the git remote's, not this process's.

    The ref is created once and then lives forever, alternating between an `active` record and a
    `tombstone` record. Nothing here deletes it — the environment these runs execute in refuses
    ref deletion outright, and a lock whose release depends on an operation the environment
    refuses is not a lock.
    """

    remote: str
    workdir: Path
    namespace: str = "refs/heads/vcrp-automation/locks"
    #: Unique to this store instance, and therefore to this run. This is what makes the lock
    #: commit unforgeably distinct from every other contender's.
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))
    _held: dict[str, str] = field(default_factory=dict, repr=False)

    def ref(self, key: str) -> str:
        return f"{self.namespace}/{_safe(key)}"

    # --- reading ------------------------------------------------------------------------------

    def _sha(self, key: str) -> str | None:
        return _remote_sha(self.remote, self.ref(key), workdir=self.workdir)

    def _record(self, key: str, sha: str) -> LockRecord:
        """Fetch the commit and parse its `lock.json`. Anything unreadable is LockCorrupt."""
        peek = f"refs/vcrp-lock-peek/{_safe(key)}"
        fetched = _git(self.workdir, "fetch", "--quiet", self.remote, f"+{self.ref(key)}:{peek}")
        if fetched.returncode != 0:
            raise LockUnavailable(f"cannot fetch the lock ref: {fetched.stderr.strip()}")
        shown = _git(self.workdir, "show", f"{sha}:{LOCK_FILE}")
        _git(self.workdir, "update-ref", "-d", peek)
        if shown.returncode != 0:
            if self._sha(key) != sha:
                # It moved between the read and the fetch. A race is not corruption, and the
                # caller may try again; saying "corrupt" here would strand a healthy lock.
                raise LockUnavailable(f"{self.ref(key)} moved while it was being read")
            raise LockCorrupt(f"{self.ref(key)} at {sha[:12]} carries no {LOCK_FILE}")

        where = f"{self.ref(key)} at {sha[:12]}"
        record = LockRecord.parse(shown.stdout, where=where)
        # The record has to be about *this* ref. A lock.json naming another work item is either
        # a mistake or a copy, and either way it is not evidence about this work item's lock.
        if record.work_id != key:
            raise LockCorrupt(f"{where} carries work id {record.work_id!r}, not {key!r}")
        # And its claim about what it replaced has to match what git actually recorded. The JSON
        # is written by the same process that builds the commit, so a disagreement between them
        # means one of the two was edited afterwards.
        if record.previous:
            parents = self._parents(sha)
            if parents != (record.previous,):
                found = ", ".join(p[:12] for p in parents) or "(none)"
                raise LockCorrupt(
                    f"{where} names previous {record.previous[:12]} but its commit's parents "
                    f"are {found}"
                )
        return record

    def _parents(self, sha: str) -> tuple[str, ...]:
        """The commit's parents, as git records them. Unreadable is blocked, never assumed."""
        listed = _git(self.workdir, "rev-list", "--parents", "-n", "1", sha)
        if listed.returncode != 0:
            problem = (listed.stderr or listed.stdout).strip()
            raise LockUnavailable(f"cannot read the parents of {sha[:12]}: {problem}")
        return tuple(listed.stdout.split()[1:])

    def state_of(self, key: str) -> tuple[str | None, LockRecord | None]:
        """The remote's current SHA and record, or (None, None) when the ref does not exist."""
        sha = self._sha(key)
        if sha is None:
            return None, None
        return sha, self._record(key, sha)

    def held_token(self, key: str) -> str | None:
        """The SHA of the *active* lock on the remote, or None when nothing holds it.

        A tombstone is not a held lock, which is why this returns None for one: the ref outlives
        every run, so "the ref exists" stopped being the same question as "somebody holds it".
        """
        sha, record = self.state_of(key)
        if sha is None or record is None:
            return None
        return sha if record.active else None

    def token_for(self, key: str) -> str | None:
        """The commit this run pushed, which is what proves ownership later."""
        return self._held.get(key)

    def holder(self, key: str) -> str:
        try:
            _, record = self.state_of(key)
        except (LockUnavailable, LockCorrupt) as error:
            return f"unreadable ({error})"
        return record.describe() if record else ""

    # --- writing ------------------------------------------------------------------------------

    def _commit(self, record: LockRecord, *, parent: str | None) -> str:
        blob = _git(self.workdir, "hash-object", "-w", "--stdin", stdin=record.as_json())
        if blob.returncode != 0:
            raise LockUnavailable(f"cannot write the lock record: {blob.stderr.strip()}")
        entry = f"100644 blob {blob.stdout.strip()}\t{LOCK_FILE}\n"
        tree = _git(self.workdir, "mktree", stdin=entry)
        if tree.returncode != 0:
            raise LockUnavailable(f"cannot build a lock tree: {tree.stderr.strip()}")
        args = ["commit-tree", tree.stdout.strip()]
        if parent:
            args += ["-p", parent]
        message = f"{record.state} {record.work_id} generation {record.generation}\n"
        commit = _git(self.workdir, *args, stdin=message)
        if commit.returncode != 0:
            raise LockUnavailable(f"cannot build a lock commit: {commit.stderr.strip()}")
        return commit.stdout.strip()

    def _push(self, key: str, sha: str, *, lease: str | None) -> _PushAttempt:
        """Attempt the write. Whether it *worked* is decided by re-reading, never by this."""
        args = ["push"]
        if lease is not None:
            args.append(f"--force-with-lease={self.ref(key)}:{lease}")
        args += [self.remote, f"{sha}:{self.ref(key)}"]
        pushed = _git(self.workdir, *args)
        combined = (pushed.stderr + pushed.stdout).lower()
        return _PushAttempt(
            exited_zero=pushed.returncode == 0,
            contention=any(word in combined for word in _CONTENTION),
            problem=(pushed.stderr or pushed.stdout).strip(),
        )

    def _landed(self, key: str, commit: str, attempt: _PushAttempt, what: str) -> bool:
        """Did the write actually take? Contention says no; a lie about it says so out loud."""
        if self._sha(key) == commit:
            return True
        if attempt.contention:
            return False  # somebody got there first, which is an outcome, not a failure
        if attempt.exited_zero:
            # The environment's refused delete did exactly this: HTTP 403 in stderr, the words
            # "Everything up-to-date", and exit 0. Believing the exit code reports a lock as
            # released while it is still held.
            raise LockUnavailable(
                f"the {what} of {self.ref(key)} reported success but the remote does not carry "
                f"{commit[:12]}: {attempt.problem or 'no diagnostic'}"
            )
        raise LockUnavailable(f"cannot {what} {self.ref(key)}: {attempt.problem}")

    def create_exclusive(self, key: str, owner: str) -> bool:
        """Take the lock, or report that somebody else has it. True only for the winner."""
        sha, record = self.state_of(key)
        if record is not None and record.active:
            return False

        generation = (record.generation + 1) if record is not None else 1
        wanted = LockRecord(
            schema=LOCK_SCHEMA,
            work_id=key,
            state=STATE_ACTIVE,
            owner=owner,
            nonce=self.nonce,
            generation=generation,
            acquired_at=_now(),
            previous=sha or "",
        )
        # Parented on the tombstone it replaces, so a contender that read the same tombstone
        # cannot fast-forward over the winner even without the lease.
        commit = self._commit(wanted, parent=sha)
        attempt = self._push(key, commit, lease=sha)
        if not self._landed(key, commit, attempt, "acquisition"):
            return False
        self._held[key] = commit
        return True

    def release(self, key: str, owner: str = "", *, token: str | None = None) -> bool:
        """Retire this run's lock by replacing it with a tombstone. Never by deleting the ref.

        ``token`` is the active lock commit's SHA, which a later process reads from the durable
        token file, so the process that releases need not be the one that took it.
        """
        active = token or self._held.get(key)
        if active is None:
            return False

        current = self._sha(key)
        if current is None or current != active:
            # Either the ref went missing, or a later generation holds it. Not ours to retire.
            return False
        record = self._record(key, current)
        if not record.active:
            return False

        tombstone = LockRecord(
            schema=LOCK_SCHEMA,
            work_id=record.work_id,
            state=STATE_TOMBSTONE,
            owner=record.owner,
            nonce=record.nonce,
            generation=record.generation,
            acquired_at=record.acquired_at,
            released_at=_now(),
            previous=current,
            release_nonce=self.nonce,
        )
        commit = self._commit(tombstone, parent=current)
        attempt = self._push(key, commit, lease=current)

        # The exit code is not the answer. A refused delete once printed "Everything up-to-date"
        # and exited 0, so success is: the remote points at the commit this process built, and
        # the object there parses as a tombstone.
        if not self._landed(key, commit, attempt, "release"):
            return self._already_retired(key, active)
        if self._record(key, commit).state != STATE_TOMBSTONE:
            raise LockCorrupt(f"{self.ref(key)} accepted a release that is not a tombstone")
        self._held.pop(key, None)
        return True

    def _already_retired(self, key: str, active: str) -> bool:
        """Lost the release race — but to whom?

        Only a process holding the same token can race a release, so the honest question is not
        "did my commit land" but "is the lock I held still active". A tombstone descending from
        exactly this run's active commit means it is not: somebody made the transition, and the
        postcondition this call exists to establish holds. Anything else is a failure.
        """
        sha, record = self.state_of(key)
        if sha is None or record is None or record.active or record.previous != active:
            return False
        self._held.pop(key, None)
        return True


@dataclass
class GitRefStateStore:
    """Small durable facts - which revision instructions have been carried out - in a ref.

    Fail-closed, because the failure mode is duplicate work: reading an unreachable remote as
    "nothing has been applied" is exactly how an approved revision gets carried out twice. And
    append-only, so unlike the lock it never needs a ref to go away.
    """

    remote: str
    workdir: Path
    ref: str = "refs/heads/vcrp-automation/state/applied-revisions"
    retries: int = 3

    def _remote_sha(self) -> str | None:
        """The ref's current value, None when it genuinely does not exist. Raises when unsure."""
        return _remote_sha(self.remote, self.ref, workdir=self.workdir)

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
        """Add one id and publish it, as a compare-and-swap that retries on a lost race.

        Success is what the **remote** holds afterwards, not what the push returned: the same
        403 that printed `Everything up-to-date` and exited 0 for a delete would otherwise be
        read here as "recorded", and a revision believed applied is a revision never applied.
        """
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
            last = (pushed.stderr or pushed.stdout).strip()

            landed = self._remote_sha()
            if landed == commit and identifier in self.load():
                return frozenset(current)
        raise LockUnavailable(
            f"could not publish durable state after {self.retries} tries; the remote does not "
            f"carry {identifier}: {last}"
        )

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
