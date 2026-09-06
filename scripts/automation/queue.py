"""The queue read, shaped so that a failure cannot be mistaken for an empty queue.

`list_issues` returning `[]` and `list_issues` raising a 403 are the same thing to any caller
that stores the result in a list: both are falsy, both iterate zero times. This type refuses
that collapse. A failed read has ``issues is None`` - there is no list to iterate, so the
mistake stops being a judgement call and becomes an attribute error.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueIssue:
    """One approved work item, as read from GitHub."""

    number: int
    title: str
    body: str


@dataclass(frozen=True)
class QueueRead:
    """The outcome of querying for approved issues: either the issues, or why there are none."""

    issues: tuple[QueueIssue, ...] | None
    error: str | None = None

    @classmethod
    def ok(cls, issues: Iterable[QueueIssue]) -> QueueRead:
        return cls(issues=tuple(issues), error=None)

    @classmethod
    def failed(cls, error: str) -> QueueRead:
        return cls(issues=None, error=error)

    @property
    def succeeded(self) -> bool:
        return self.issues is not None
