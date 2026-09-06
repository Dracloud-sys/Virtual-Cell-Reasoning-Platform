"""Question 6, raced for real: two containers cannot see each other's filesystem, but both
push to the same remote.

`FileLockStore` is atomic within one container and blind outside it, which is the wrong shape
for scheduled runs — each gets its own container and its own empty lock directory. The store
under test here puts the lock where both runs can reach it and lets git decide: pushing an
**orphan** commit to a ref cannot fast-forward whatever is already there, so while the ref
exists every other push is rejected by the server.

These tests do not simulate contention. They start real threads that each run real `git push`
against one real bare repository, released together from a barrier, and assert that exactly one
of them came back holding the lock. The previous round's concurrency test called the store
twice in sequence, which demonstrates bookkeeping and nothing about a race.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from automation.gitrefs import (
    GitRefLockStore,
    GitRefStateStore,
    LockUnavailable,
    StateCorrupt,
)

RUNNERS = 6

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


def test_one_push_wins_and_the_rest_are_told_so(remote: Path, workdir: Path) -> None:
    assert _store(remote, workdir).create_exclusive("vcrp-ops-001", "runner-a") is True
    assert _store(remote, workdir).create_exclusive("vcrp-ops-001", "runner-b") is False


def test_exactly_one_of_six_concurrent_runners_takes_the_lock(remote: Path, tmp_path: Path) -> None:
    """A real race: six threads, one barrier, six `git push` processes, one shared remote."""
    barrier = Barrier(RUNNERS)
    workdirs = []
    for index in range(RUNNERS):
        work = tmp_path / f"runner-{index}"
        work.mkdir()
        _git("init", "--quiet", cwd=work)
        workdirs.append(work)

    def contend(index: int) -> bool:
        store = _store(remote, workdirs[index])
        barrier.wait()
        return store.create_exclusive("vcrp-ops-001", f"runner-{index}")

    with ThreadPoolExecutor(max_workers=RUNNERS) as pool:
        results = list(pool.map(contend, range(RUNNERS)))

    assert sum(results) == 1, results


def test_the_holder_is_readable_by_a_runner_that_lost(remote: Path, workdir: Path) -> None:
    _store(remote, workdir).create_exclusive("vcrp-ops-001", "runner-a")

    assert "runner-a" in _store(remote, workdir).holder("vcrp-ops-001")


def test_only_the_holder_can_release(remote: Path, workdir: Path) -> None:
    """A crashed run is exactly when another run would love to clear the lock and start."""
    winner = _store(remote, workdir)
    winner.create_exclusive("vcrp-ops-001", "runner-a")

    loser = _store(remote, workdir)
    assert loser.release("vcrp-ops-001", "runner-b") is False
    assert loser.create_exclusive("vcrp-ops-001", "runner-b") is False

    assert winner.release("vcrp-ops-001", "runner-a") is True
    assert loser.create_exclusive("vcrp-ops-001", "runner-b") is True


def test_an_unreachable_remote_raises_rather_than_reporting_a_free_lock(
    tmp_path: Path, workdir: Path
) -> None:
    """ "I could not check" must never be read as "nobody else is running"."""
    store = GitRefLockStore(remote=str(tmp_path / "does-not-exist.git"), workdir=workdir)

    with pytest.raises(LockUnavailable):
        store.create_exclusive("vcrp-ops-001", "runner-a")


def test_two_keys_do_not_collide(remote: Path, workdir: Path) -> None:
    store = _store(remote, workdir)

    assert store.create_exclusive("vcrp-ops-001", "a") is True
    assert store.create_exclusive("vcrp-ops-002", "b") is True


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


# --- regressions from the second review round -------------------------------------------------


def test_two_runs_with_the_same_owner_in_the_same_second_do_not_both_win(
    remote: Path, tmp_path: Path, monkeypatch
) -> None:
    """The mutual exclusion was broken outright, and its own tests did not see it.

    Git objects are content-addressed. Two runs with the same work id, the same owner
    (`scheduled-runner`) and the same one-second timestamp built the *same* commit, so the
    second push found the ref already pointing at that object, git said "Everything
    up-to-date", exited 0, and both runs believed they held the lock:

        same-owner same-second lock results: [True, True]

    Pinning the clock and the owner is exactly that case.
    """
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-09-06T00:00:00+0000")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-09-06T00:00:00+0000")
    stores = []
    for name in ("a", "b"):
        work = tmp_path / f"same-{name}"
        work.mkdir()
        _git("init", "--quiet", cwd=work)
        stores.append(GitRefLockStore(remote=str(remote), workdir=work))

    results = [store.create_exclusive("vcrp-ops-001", "scheduled-runner") for store in stores]

    assert results == [True, False], results


def test_each_store_mints_a_different_lock_commit(remote: Path, workdir: Path) -> None:
    """The nonce is the mutual exclusion; the compare-and-swap only enforces it."""
    first = GitRefLockStore(remote=str(remote), workdir=workdir)
    second = GitRefLockStore(remote=str(remote), workdir=workdir)

    assert first.nonce != second.nonce


def test_a_later_process_can_release_with_the_token(remote: Path, workdir: Path) -> None:
    """The lock used to live in an instance attribute, so the first run stranded it forever."""
    taker = GitRefLockStore(remote=str(remote), workdir=workdir)
    taker.create_exclusive("vcrp-ops-001", "runner-a")
    token = taker.token_for("vcrp-ops-001")

    fresh_process = GitRefLockStore(remote=str(remote), workdir=workdir)
    assert fresh_process.release("vcrp-ops-001", "runner-a", token=token) is True
    assert fresh_process.create_exclusive("vcrp-ops-001", "runner-b") is True


def test_releasing_with_the_wrong_token_fails(remote: Path, workdir: Path) -> None:
    taker = GitRefLockStore(remote=str(remote), workdir=workdir)
    taker.create_exclusive("vcrp-ops-001", "runner-a")

    other = GitRefLockStore(remote=str(remote), workdir=workdir)
    assert other.release("vcrp-ops-001", "runner-b", token="0" * 40) is False
    assert other.create_exclusive("vcrp-ops-001", "runner-b") is False


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
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.invalid",
            "PATH": "/usr/bin:/bin",
        },
    ).stdout.strip()
    subprocess.run(
        ["git", "push", str(remote), f"{commit}:{store.ref}"],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )

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
