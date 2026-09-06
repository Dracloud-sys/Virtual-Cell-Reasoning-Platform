"""When a run may touch a pull request that is already waiting on a reviewer.

The default is that it may not. A PR under review is a question put to a person, and a run that
pushes to it while they are reading has answered a different question than the one they were
asked. The exception is narrow and has to be evidenced: an instruction that a named person
approved, that names the pull request **and the head SHA it was written against**, and that
this run has not already carried out.

The head SHA is what makes the instruction expire. "Please simplify the parser" means something
about the code that existed when it was written; once the branch moves, the same sentence is a
new request against code its author has not read. And the applied-once check is what keeps the
next scheduled run from reading the same comment and doing the work a second time.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class RevisionInstruction:
    """An approved instruction to revise one pull request at one point in its history."""

    identifier: str
    approved_by: str
    target_pull_request: int
    target_head_sha: str

    @property
    def approved(self) -> bool:
        return bool(self.approved_by.strip())


def actionable(
    instructions: Iterable[RevisionInstruction],
    *,
    pull_request: int,
    head_sha: str,
    applied_ids: Collection[str] = (),
) -> tuple[RevisionInstruction, ...]:
    """The instructions this run should carry out, in the order they were given."""
    return tuple(
        instruction
        for instruction in instructions
        if instruction.approved
        and instruction.target_pull_request == pull_request
        and instruction.target_head_sha == head_sha
        and instruction.identifier not in applied_ids
    )
