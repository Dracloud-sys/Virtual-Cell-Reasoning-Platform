"""When a run may touch a pull request that is already waiting on a reviewer.

The default is that it may not. A PR under review is a question put to a person, and a run that
pushes to it while they are reading has answered a different question than the one they were
asked. The exception is narrow, and every part of it has to be evidenced:

* **a real approval record.** Not "somebody typed a name": the instruction carries the id of
  the GitHub review or comment it came from, and the author is checked against an allow-list of
  approvers. A non-empty author string is not an approval - it is a string.
* **the pull request it names**, matched by number.
* **the head SHA it was written against**, in full. "Please simplify the parser" means something
  about the code that existed when it was written; once the branch moves, the same sentence is a
  new request about code its author has not read. Abbreviated SHAs are refused rather than
  prefix-matched, because a prefix is not an identity.
* **not already carried out.** The applied ids come from a store that outlives the session, so
  the next run reading the same comment does not do the work twice.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class RevisionInstruction:
    """An approved instruction to revise one pull request at one point in its history."""

    identifier: str
    approved_by: str
    target_pull_request: int
    target_head_sha: str
    #: The GitHub review/comment id this came from. Without it there is nothing to audit.
    approval_record_id: str = ""
    #: What was actually asked for, kept so the PR can cite it rather than paraphrase it.
    content: str = ""

    def approval_problem(self, approvers: Collection[str]) -> str | None:
        """Why this instruction may not be acted on, or None when it may."""
        if not self.approval_record_id.strip():
            return "carries no approval record id"
        if not self.approved_by.strip():
            return "names no approver"
        if approvers and self.approved_by not in approvers:
            return f"{self.approved_by!r} is not an accepted approver"
        if not _FULL_SHA.match(self.target_head_sha.strip().lower()):
            return "does not name a full 40-character head SHA"
        return None


def actionable(
    instructions: Iterable[RevisionInstruction],
    *,
    pull_request: int,
    head_sha: str,
    applied_ids: Collection[str] = (),
    approvers: Collection[str] = (),
) -> tuple[RevisionInstruction, ...]:
    """The instructions this run should carry out, in the order they were given."""
    return tuple(
        instruction
        for instruction in instructions
        if instruction.approval_problem(approvers) is None
        and instruction.target_pull_request == pull_request
        and instruction.target_head_sha.strip().lower() == head_sha.strip().lower()
        and instruction.identifier not in applied_ids
    )


def rejections(
    instructions: Iterable[RevisionInstruction],
    *,
    pull_request: int,
    head_sha: str,
    applied_ids: Collection[str] = (),
    approvers: Collection[str] = (),
) -> tuple[str, ...]:
    """Why each instruction that was not acted on was passed over. Reported, never silent."""
    reasons: list[str] = []
    for instruction in instructions:
        problem = instruction.approval_problem(approvers)
        if problem is not None:
            reasons.append(f"{instruction.identifier}: {problem}")
        elif instruction.target_pull_request != pull_request:
            reasons.append(
                f"{instruction.identifier}: names pull request #{instruction.target_pull_request}"
            )
        elif instruction.target_head_sha.strip().lower() != head_sha.strip().lower():
            reasons.append(f"{instruction.identifier}: written against a head that has moved on")
        elif instruction.identifier in applied_ids:
            reasons.append(f"{instruction.identifier}: already applied")
    return tuple(reasons)
