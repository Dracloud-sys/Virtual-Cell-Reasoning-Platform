"""What a preflight run is allowed to conclude.

Every terminal state is named, and the names are the report. The one that matters most is the
distinction between "the queue is empty" and "I could not read the queue": both leave the
repository untouched, so without separate statuses a broken token is indistinguishable from a
quiet night, and the run that silently did nothing looks exactly like the run that correctly
did nothing.
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
    INVALID_SPEC = "INVALID_SPEC"
    BLOCKED_GITHUB_ACCESS = "BLOCKED_GITHUB_ACCESS"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    BLOCKED_SCOPE = "BLOCKED_SCOPE"
    ALREADY_RUNNING = "ALREADY_RUNNING"
    AWAITING_REVIEW = "AWAITING_REVIEW"


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

    def line(self) -> str:
        return f"{self.status.value}: {self.detail}" if self.detail else self.status.value
