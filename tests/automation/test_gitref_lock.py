"""Question 6, raced for real, against a lock that is a state machine rather than a ref's
existence.

`FileLockStore` is atomic within one container and blind outside it, which is the wrong shape
for scheduled runs — each gets its own container and its own empty lock directory. The store
under test puts the lock where both runs can reach it and lets git decide.

Two things the real remote taught this file, and both changed the design rather than the tests:

* **the environment refuses ref deletion** (HTTP 403 on `git push --delete`, while creating and
  updating a branch succeeds), so releasing cannot mean deleting. A release is now a transition
  from an `active` record to a `tombstone` record, and the ref outlives every run;
* **that refused delete exited 0** and printed `Everything up-to-date`. So no write here is
  believed on its exit code: every one is followed by re-reading the remote, and the 403-shaped
  liar is reproduced below as a regression.

These tests do not simulate contention. They start real threads that each run real `git push`
against one real bare repository, released together from a barrier, and assert that exactly one
came back holding the lock — from an absent ref *and* from a shared tombstone, which is the
transition the old design never had to survive.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from automation.gitrefs import (
    LOCK_SCHEMA,
    STATE_ACTIVE,
    STATE_TOMBSTONE,
    GitRefLockStore,
    GitRefStateStore,
    LockCorrupt,
    LockRecord,
    LockUnavailable,
    StateCorrupt,
)

RUNNERS = 6
KEY = "vcrp-ops-001"

_IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t.invalid",
    "PATH": "/usr/bin:/bin",
}


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare repository standing in for the shared origin every container can reach."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git("init", "--bare", "--quiet", cwd=bare)
    return bare


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "--quiet", cwd=work)
    return work


def _store(remote: Path, workdir: Path) -> GitRefLockStore:
    return GitRefLockStore(remote=str(remote), workdir=workdir)


def _containers(tmp_path: Path, count: int, prefix: str = "runner") -> list[Path]:
    """One working copy each, because one container per run is the situation being modelled."""
    made = []
    for index in range(count):
        work = tmp_path / f"{prefix}-{index}"
        work.mkdir()
        _git("init", "--quiet", cwd=work)
        made.append(work)
    return made


def _race(remote: Path, workdirs: list[Path], key: str = KEY) -> list[bool]:
    barrier = Barrier(len(workdirs))

    def contend(index: int) -> bool:
        store = GitRefLockStore(remote=str(remote), workdir=workdirs[index])
        barrier.wait()
        return store.create_exclusive(key, f"runner-{index}")

    with ThreadPoolExecutor(max_workers=len(workdirs)) as pool:
        return list(pool.map(contend, range(len(workdirs))))


def _record_on_remote(remote: Path, workdir: Path, key: str = KEY) -> LockRecord:
    sha, record = GitRefLockStore(remote=str(remote), workdir=workdir).state_of(key)
    assert sha is not None and record is not None
    return record


# --- the lifecycle ----------------------------------------------------------------------------


def test_one_push_wins_and_the_rest_are_told_so(remote: Path, workdir: Path) -> None:
    assert _store(remote, workdir).create_exclusive(KEY, "runner-a") is True
    assert _store(remote, workdir).create_exclusive(KEY, "runner-b") is False


def test_the_lock_record_is_structured_rather_than_a_message_to_grep(
    remote: Path, workdir: Path
) -> None:
    """Nothing decides anything by substring: the state is a field in a JSON document."""
    _store(remote, workdir).create_exclusive(KEY, "runner-a")

    record = _record_on_remote(remote, workdir)

    assert record.schema == LOCK_SCHEMA
    assert (record.work_id, record.state, record.owner) == (KEY, STATE_ACTIVE, "runner-a")
    assert record.generation == 1
    assert record.nonce and record.acquired_at
    assert record.previous == ""


def test_releasing_leaves_a_tombstone_rather_than_deleting_the_ref(
    remote: Path, workdir: Path
) -> None:
    """The environment refuses deletion, so the ref has to survive its own release."""
    store = _store(remote, workdir)
    store.create_exclusive(KEY, "runner-a")
    active = store.token_for(KEY)

    assert store.release(KEY, "runner-a") is True

    record = _record_on_remote(remote, workdir)
    assert record.state == STATE_TOMBSTONE
    assert record.previous == active
    assert record.released_at
    assert _store(remote, workdir).held_token(KEY) is None  # a tombstone is not a held lock


def test_a_tombstoned_lock_can_be_taken_again_with_a_higher_generation(
    remote: Path, workdir: Path
) -> None:
    first = _store(remote, workdir)
    first.create_exclusive(KEY, "runner-a")
    first.release(KEY, "runner-a")

    assert _store(remote, workdir).create_exclusive(KEY, "runner-b") is True

    record = _record_on_remote(remote, workdir)
    assert (record.state, record.owner, record.generation) == (STATE_ACTIVE, "runner-b", 2)


def test_the_ref_is_never_deleted_across_a_whole_lifecycle(remote: Path, workdir: Path) -> None:
    store = _store(remote, workdir)
    seen = []
    for owner in ("a", "b", "c"):
        store.create_exclusive(KEY, owner)
        seen.append(_record_on_remote(remote, workdir).state)
        store.release(KEY, owner)
        seen.append(_record_on_remote(remote, workdir).state)

    assert seen == [STATE_ACTIVE, STATE_TOMBSTONE] * 3


# --- concurrency, on a real remote ------------------------------------------------------------


def test_exactly_one_of_six_concurrent_runners_takes_an_absent_lock(
    remote: Path, tmp_path: Path
) -> None:
    """A real race: six threads, one barrier, six `git push` processes, one shared remote."""
    results = _race(remote, _containers(tmp_path, RUNNERS))

    assert sum(results) == 1, results


def test_every_contender_is_refused_while_the_lock_is_active(remote: Path, tmp_path: Path) -> None:
    holders = _containers(tmp_path, 1, "holder")
    GitRefLockStore(remote=str(remote), workdir=holders[0]).create_exclusive(KEY, "holder")

    results = _race(remote, _containers(tmp_path, RUNNERS))

    assert results == [False] * RUNNERS


def test_exactly_one_of_six_concurrent_runners_takes_a_tombstoned_lock(
    remote: Path, tmp_path: Path
) -> None:
    """The transition the old design never had: six contenders all reading the same tombstone."""
    first = _containers(tmp_path, 1, "first")[0]
    holder = GitRefLockStore(remote=str(remote), workdir=first)
    holder.create_exclusive(KEY, "holder")
    holder.release(KEY, "holder")

    results = _race(remote, _containers(tmp_path, RUNNERS))

    assert sum(results) == 1, results
    assert _record_on_remote(remote, first).generation == 2


def test_a_token_from_an_earlier_generation_cannot_release_the_current_lock(
    remote: Path, workdir: Path
) -> None:
    first = _store(remote, workdir)
    first.create_exclusive(KEY, "runner-a")
    stale_token = first.token_for(KEY)
    first.release(KEY, "runner-a")
    second = _store(remote, workdir)
    second.create_exclusive(KEY, "runner-b")

    assert _store(remote, workdir).release(KEY, "runner-a", token=stale_token) is False
    assert _record_on_remote(remote, workdir).owner == "runner-b"
    assert _store(remote, workdir).held_token(KEY) == second.token_for(KEY)


def test_two_releases_racing_leave_exactly_one_transition(remote: Path, tmp_path: Path) -> None:
    """Both hold the same token, so only one of them can be the transition that happened.

    Both are allowed to *report* success — the postcondition each was called to establish is
    "the lock I held is no longer active", and a tombstone descending from that exact commit
    establishes it for both. What must not happen is two transitions, and that is what the
    single surviving `release_nonce` shows. Without a per-release nonce the two tombstones were
    byte-identical, so git stored one object and both processes saw "their" commit on the
    remote — the same content-addressing collision that once produced `[True, True]` on acquire.
    """
    first = _containers(tmp_path, 1, "holder")[0]
    holder = GitRefLockStore(remote=str(remote), workdir=first)
    holder.create_exclusive(KEY, "holder")
    token = holder.token_for(KEY)
    workdirs = _containers(tmp_path, 2, "releaser")
    stores = [GitRefLockStore(remote=str(remote), workdir=work) for work in workdirs]
    barrier = Barrier(2)

    def release(index: int) -> bool:
        barrier.wait()
        try:
            return stores[index].release(KEY, "holder", token=token)
        except LockUnavailable:
            # A write of ours that the remote did not accept is a failure to release, never a
            # second release, and it must never be reported as success.
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(release, range(2)))

    record = _record_on_remote(remote, first)
    assert results == [True, True], results
    assert record.state == STATE_TOMBSTONE
    assert record.previous == token
    # Exactly one of the two processes made the transition on the remote.
    assert [store.nonce for store in stores].count(record.release_nonce) == 1


def test_a_later_process_can_release_with_the_token(remote: Path, workdir: Path) -> None:
    """The lock used to live in an instance attribute, so the first run stranded it forever."""
    taker = GitRefLockStore(remote=str(remote), workdir=workdir)
    taker.create_exclusive(KEY, "runner-a")
    token = taker.token_for(KEY)

    fresh_process = GitRefLockStore(remote=str(remote), workdir=workdir)
    assert fresh_process.release(KEY, "runner-a", token=token) is True
    assert fresh_process.create_exclusive(KEY, "runner-b") is True


def test_two_keys_do_not_collide(remote: Path, workdir: Path) -> None:
    store = _store(remote, workdir)

    assert store.create_exclusive("vcrp-ops-001", "a") is True
    assert store.create_exclusive("vcrp-ops-002", "b") is True


def test_each_store_mints_a_different_lock_commit(remote: Path, workdir: Path) -> None:
    """The nonce is the mutual exclusion; the compare-and-swap only enforces it."""
    assert _store(remote, workdir).nonce != _store(remote, workdir).nonce


def test_two_runs_with_the_same_owner_in_the_same_second_do_not_both_win(
    remote: Path, tmp_path: Path, monkeypatch
) -> None:
    """Git objects are content-addressed, and this case once produced `[True, True]`.

    Two runs with the same work id, the same owner and the same one-second timestamp built the
    *same* commit, so the second push found the ref already pointing at that object, git said
    "Everything up-to-date", exited 0, and both runs believed they held the lock.
    """
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-09-06T00:00:00+0000")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-09-06T00:00:00+0000")
    stores = [
        GitRefLockStore(remote=str(remote), workdir=work)
        for work in _containers(tmp_path, 2, "same")
    ]

    results = [store.create_exclusive(KEY, "scheduled-runner") for store in stores]

    assert results == [True, False], results


# --- fail-closed reading ----------------------------------------------------------------------


def test_an_unreachable_remote_raises_rather_than_reporting_a_free_lock(
    tmp_path: Path, workdir: Path
) -> None:
    """ "I could not check" must never be read as "nobody else is running"."""
    store = GitRefLockStore(remote=str(tmp_path / "does-not-exist.git"), workdir=workdir)

    with pytest.raises(LockUnavailable):
        store.create_exclusive(KEY, "runner-a")


def _push_lock_blob(remote: Path, workdir: Path, payload: str, ref: str) -> None:
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=workdir,
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "mktree"],
        cwd=workdir,
        input=f"100644 blob {blob}\tlock.json\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "commit-tree", tree],
        cwd=workdir,
        input="hand-written",
        capture_output=True,
        text=True,
        check=True,
        env=_IDENTITY,
    ).stdout.strip()
    _git("push", str(remote), f"{commit}:{ref}", cwd=workdir)


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        json.dumps({"schema": "something-else/9", "state": "active"}),
        json.dumps({"schema": LOCK_SCHEMA, "state": "half-open"}),
        json.dumps({"schema": LOCK_SCHEMA, "state": "tombstone", "work_id": "x"}),
    ],
    ids=["not-json", "unknown-schema", "unknown-state", "missing-fields"],
)
def test_a_lock_record_that_does_not_parse_is_not_a_free_lock(
    remote: Path, workdir: Path, payload: str
) -> None:
    store = _store(remote, workdir)
    _push_lock_blob(remote, workdir, payload, store.ref(KEY))

    with pytest.raises(LockCorrupt):
        store.held_token(KEY)
    with pytest.raises(LockCorrupt):
        store.create_exclusive(KEY, "runner-a")


def test_a_lock_commit_without_a_record_is_not_a_free_lock(remote: Path, workdir: Path) -> None:
    store = _store(remote, workdir)
    empty_tree = subprocess.run(
        ["git", "mktree"], cwd=workdir, input="", capture_output=True, text=True, check=True
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "commit-tree", empty_tree],
        cwd=workdir,
        input="no lock.json here",
        capture_output=True,
        text=True,
        check=True,
        env=_IDENTITY,
    ).stdout.strip()
    _git("push", str(remote), f"{commit}:{store.ref(KEY)}", cwd=workdir)

    with pytest.raises(LockCorrupt):
        store.create_exclusive(KEY, "runner-a")


# --- the regression that made this redesign necessary -----------------------------------------


class _LyingGit:
    """A `git` that refuses the write the way the real environment did: 403, and exit 0.

    Observed on the real origin, verbatim: HTTP 403 on `git-receive-pack`, the words
    "Everything up-to-date" on stdout, and a return code of **0**, with the remote ref left
    exactly where it was. A store that believes exit codes reports that lock as released.
    """

    def __init__(self, real, *, refuse: str) -> None:
        self.real = real
        self.refuse = refuse
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, workdir, *args, stdin=None):
        self.calls.append(args)
        if args and args[0] == "push" and any(self.refuse in arg for arg in args):
            return subprocess.CompletedProcess(
                args=["git", *args],
                returncode=0,
                stdout="Everything up-to-date\n",
                stderr="error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403\n"
                "send-pack: unexpected disconnect while reading sideband packet\n",
            )
        return self.real(workdir, *args, stdin=stdin)


def test_a_push_that_lies_about_succeeding_does_not_release_the_lock(
    remote: Path, workdir: Path, monkeypatch
) -> None:
    import automation.gitrefs as gitrefs

    store = _store(remote, workdir)
    store.create_exclusive(KEY, "runner-a")
    active = store.token_for(KEY)
    monkeypatch.setattr(gitrefs, "_git", _LyingGit(gitrefs._git, refuse="force-with-lease"))

    with pytest.raises(LockUnavailable) as raised:
        store.release(KEY, "runner-a")

    assert "does not carry" in str(raised.value)
    assert _record_on_remote(remote, workdir).state == STATE_ACTIVE
    assert _store(remote, workdir).held_token(KEY) == active


def test_a_push_that_lies_about_succeeding_does_not_take_the_lock(
    remote: Path, workdir: Path, monkeypatch
) -> None:
    import automation.gitrefs as gitrefs

    monkeypatch.setattr(gitrefs, "_git", _LyingGit(gitrefs._git, refuse=":refs/heads/"))
    store = _store(remote, workdir)

    with pytest.raises(LockUnavailable):
        store.create_exclusive(KEY, "runner-a")


def test_a_release_succeeds_when_the_remote_agrees_however_odd_the_output(
    remote: Path, workdir: Path, monkeypatch
) -> None:
    """The converse: noisy output is not a failure. Only the remote's own answer decides."""
    import automation.gitrefs as gitrefs

    store = _store(remote, workdir)
    store.create_exclusive(KEY, "runner-a")
    real = gitrefs._git

    def noisy(workdir_, *args, stdin=None):
        done = real(workdir_, *args, stdin=stdin)
        if args and args[0] == "push":
            return subprocess.CompletedProcess(
                args=done.args,
                returncode=1,
                stdout=done.stdout + "warning: push negotiation failed; proceeding anyway\n",
                stderr=done.stderr,
            )
        return done

    monkeypatch.setattr(gitrefs, "_git", noisy)

    assert store.release(KEY, "runner-a") is True
    assert _record_on_remote(remote, workdir).state == STATE_TOMBSTONE


# --- durable state ----------------------------------------------------------------------------


def test_applied_revisions_survive_the_session(remote: Path, workdir: Path) -> None:
    """A restarted run must not redo work its predecessor already did."""
    store = GitRefStateStore(remote=str(remote), workdir=workdir)
    assert store.load() == frozenset()

    store.record("comment-9001")

    fresh_container = GitRefStateStore(remote=str(remote), workdir=workdir)
    assert "comment-9001" in fresh_container.load()


def test_recording_twice_is_idempotent(remote: Path, workdir: Path) -> None:
    store = GitRefStateStore(remote=str(remote), workdir=workdir)
    store.record("comment-9001")
    store.record("comment-9001")

    assert store.load() == frozenset({"comment-9001"})


def test_state_accumulates_across_runs(remote: Path, workdir: Path) -> None:
    GitRefStateStore(remote=str(remote), workdir=workdir).record("comment-1")
    GitRefStateStore(remote=str(remote), workdir=workdir).record("comment-2")

    assert GitRefStateStore(remote=str(remote), workdir=workdir).load() == frozenset(
        {"comment-1", "comment-2"}
    )


def test_missing_state_reads_as_empty_not_as_an_error(remote: Path, workdir: Path) -> None:
    """A ref that does not exist yet genuinely is an empty set — that much is safe."""
    assert GitRefStateStore(remote=str(remote), workdir=workdir).load() == frozenset()


def test_a_state_push_that_lies_about_succeeding_is_not_a_recording(
    remote: Path, workdir: Path, monkeypatch
) -> None:
    """Believing the exit code here means a revision is 'applied' while nothing was written."""
    import automation.gitrefs as gitrefs

    store = GitRefStateStore(remote=str(remote), workdir=workdir)
    store.record("comment-1")
    monkeypatch.setattr(gitrefs, "_git", _LyingGit(gitrefs._git, refuse="force-with-lease"))

    with pytest.raises(LockUnavailable):
        store.record("comment-2")

    monkeypatch.undo()
    assert store.load() == frozenset({"comment-1"})


def test_an_unreachable_state_remote_blocks_rather_than_reading_as_empty(
    tmp_path: Path, workdir: Path
) -> None:
    """ "No revisions have been applied" out of a failed fetch applies an approved one twice."""
    store = GitRefStateStore(remote=str(tmp_path / "absent.git"), workdir=workdir)

    with pytest.raises(LockUnavailable):
        store.load()


def test_malformed_state_is_blocked_separately_from_unreachable(
    remote: Path, workdir: Path
) -> None:
    store = GitRefStateStore(remote=str(remote), workdir=workdir)
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=workdir,
        input="{not json",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "mktree"],
        cwd=workdir,
        input=f"100644 blob {blob}\tapplied.json\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "commit-tree", tree],
        cwd=workdir,
        input="bad state",
        capture_output=True,
        text=True,
        check=True,
        env=_IDENTITY,
    ).stdout.strip()
    _git("push", str(remote), f"{commit}:{store.ref}", cwd=workdir)

    with pytest.raises(StateCorrupt):
        store.load()


def test_recording_state_uses_a_lease_rather_than_a_blind_force(
    remote: Path, workdir: Path
) -> None:
    """A blind --force loses whatever another run recorded between the read and the write."""
    store = GitRefStateStore(remote=str(remote), workdir=workdir)
    store.record("comment-1")
    store.record("comment-2")

    assert store.load() == frozenset({"comment-1", "comment-2"})
