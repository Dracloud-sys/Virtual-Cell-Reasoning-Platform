"""What a preflight run is allowed to conclude, and what the shell learns from it.

Every terminal state is named, and the names are the report. The one that matters most is the
distinction between "the queue is empty" and "I could not read the queue": both leave the
repository untouched, so without separate statuses a broken token is indistinguishable from a
quiet night, and the run that silently did nothing looks exactly like the run that correctly
did nothing.

Each status also carries a distinct **exit code**, because the entry point is a process and a
caller that only sees zero-or-one has to parse prose to find out what happened. Zero means one
thing only: work may begin.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    """Terminal states of the preflight gate."""

    READY_TO_IMPLEMENT = "READY_TO_IMPLEMENT"
    NO_READY_WORK = "NO_READY_WORK"
    AMBIGUOUS_QUEUE = "AMBIGUOUS_QUEUE"
    AMBIGUOUS_PULL_REQUEST = "AMBIGUOUS_PULL_REQUEST"
    INVALID_SPEC = "INVALID_SPEC"
    WORK_ID_MISMATCH = "WORK_ID_MISMATCH"
    BLOCKED_GITHUB_ACCESS = "BLOCKED_GITHUB_ACCESS"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    BLOCKED_SCOPE = "BLOCKED_SCOPE"
    ALREADY_RUNNING = "ALREADY_RUNNING"
    AWAITING_REVIEW = "AWAITING_REVIEW"


#: Process exit codes. Only READY_TO_IMPLEMENT is 0 — a caller that treats any other status as
#: success has already made the mistake this package exists to prevent.
EXIT_CODES: Mapping[Status, int] = {
    Status.READY_TO_IMPLEMENT: 0,
    Status.NO_READY_WORK: 10,
    Status.AMBIGUOUS_QUEUE: 11,
    Status.INVALID_SPEC: 12,
    Status.BLOCKED_GITHUB_ACCESS: 13,
    Status.BLOCKED_ENVIRONMENT: 14,
    Status.BLOCKED_SCOPE: 15,
    Status.ALREADY_RUNNING: 16,
    Status.AWAITING_REVIEW: 17,
    Status.WORK_ID_MISMATCH: 18,
    Status.AMBIGUOUS_PULL_REQUEST: 19,
}


@dataclass(frozen=True)
class Outcome:
    """A decision, the sentence that explains it, and whatever a report needs to cite."""

    status: Status
    detail: str = ""
    evidence: Mapping[str, str] = field(default_factory=dict)

    @property
    def proceeds(self) -> bool:
        """Only one status opens the door. Everything else stops the run."""
        return self.status is Status.READY_TO_IMPLEMENT

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.status]

    def line(self) -> str:
        return f"{self.status.value}: {self.detail}" if self.detail else self.status.value

    def with_evidence(self, **extra: str) -> Outcome:
        return Outcome(self.status, self.detail, {**self.evidence, **extra})
