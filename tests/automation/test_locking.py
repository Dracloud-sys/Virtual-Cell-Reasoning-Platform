"""Question 6, at the level of the primitive: the lock has to be atomic, not advisory.

A prompt that says "do not start if another run is going" is not a lock. It is a request, made
to the one party that cannot check whether the other party read it. So the store exposes a
single operation - create this key, and tell me whether *I* was the one who created it - and
every caller learns the answer from the filesystem or the remote, never from its own memory.

``FileLockStore`` covers one container. It cannot see a run in a different container, which is
where scheduled runs actually live; ``docs/operations/routine_runbook.md`` records that gap and
what closes it.
"""

from __future__ import annotations

from pathlib import Path

from automation.locking import FileLockStore, InMemoryLockStore, LockStore, acquire
from automation.outcomes import Status


def _exercise_exclusivity(store: LockStore) -> None:
    assert store.create_exclusive("vcrp-ops-001", "runner-a") is True
    assert store.create_exclusive("vcrp-ops-001", "runner-b") is False


def test_in_memory_store_admits_one_holder() -> None:
    _exercise_exclusivity(InMemoryLockStore())


def test_file_store_admits_one_holder(tmp_path: Path) -> None:
    """O_CREAT|O_EXCL is the atom: the loser gets a refusal, not a second lock."""
    _exercise_exclusivity(FileLockStore(tmp_path))


def test_file_store_records_who_holds_the_lock(tmp_path: Path) -> None:
    store = FileLockStore(tmp_path)
    store.create_exclusive("vcrp-ops-001", "runner-a")

    assert "runner-a" in store.holder("vcrp-ops-001")


def test_release_lets_the_next_run_start(tmp_path: Path) -> None:
    store = FileLockStore(tmp_path)
    store.create_exclusive("vcrp-ops-001", "runner-a")
    store.release("vcrp-ops-001")

    assert store.create_exclusive("vcrp-ops-001", "runner-b") is True


def test_releasing_a_lock_nobody_holds_is_not_an_error(tmp_path: Path) -> None:
    """Recovery runs after a crash, where the lock may or may not still be there."""
    FileLockStore(tmp_path).release("vcrp-ops-001")


def test_two_keys_do_not_collide(tmp_path: Path) -> None:
    store = FileLockStore(tmp_path)

    assert store.create_exclusive("vcrp-ops-001", "a") is True
    assert store.create_exclusive("vcrp-ops-002", "b") is True


def test_acquire_reports_already_running_rather_than_raising() -> None:
    store = InMemoryLockStore()
    first = acquire(store, "vcrp-ops-001", owner="runner-a")
    second = acquire(store, "vcrp-ops-001", owner="runner-b")

    assert first.status is Status.READY_TO_IMPLEMENT
    assert second.status is Status.ALREADY_RUNNING
    assert "runner-a" in second.detail


def test_key_is_confined_to_one_path_segment(tmp_path: Path) -> None:
    """A work id is attacker-adjacent input; it must not escape the lock directory."""
    store = FileLockStore(tmp_path)
    store.create_exclusive("../escape", "runner-a")

    assert not (tmp_path.parent / "escape.lock").exists()
    assert list(tmp_path.iterdir())
