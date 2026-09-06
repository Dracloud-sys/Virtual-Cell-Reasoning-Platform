"""Turning what GitHub actually returns into the facts the gate decides from.

The gate is pure, so something has to read real responses, and this is it. It is separate from
`preflight` because parsing is where the interesting mistakes live, and they are all the same
mistake in different clothes: **treating a partial or failed answer as a complete one.**

Three of them are handled here explicitly.

* **An error is not an empty list.** A payload carrying an error produces a failed
  :class:`~automation.queue.QueueRead`, which has no list to iterate.
* **A page is not the queue.** If the response says another page exists and no further page was
  supplied, the read is *incomplete* — and an incomplete read that happens to show one issue
  would send a run off to implement it while a second approved issue sat on page two. That is a
  failed read, not a queue of one.
* **A closed issue carrying the label is not queued.** The queue is open issues only; the
  filter is applied here rather than trusted from the caller's query arguments, because a
  caller that forgot `state=OPEN` would otherwise dispatch work from a closed issue.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .preflight import LinkedPullRequest
from .queue import QueueIssue, QueueRead
from .spec_contract import extract_work_id

#: The label a person applies when they approve an issue for an unattended run.
APPROVAL_LABEL = "claude-ready"


def _labels(issue: Mapping[str, Any]) -> set[str]:
    """Labels arrive either as strings or as objects with a name, depending on the endpoint."""
    out: set[str] = set()
    for label in issue.get("labels") or ():
        if isinstance(label, str):
            out.add(label)
        elif isinstance(label, Mapping):
            name = label.get("name")
            if isinstance(name, str):
                out.add(name)
    return out


def _is_open(issue: Mapping[str, Any]) -> bool:
    state = issue.get("state")
    return isinstance(state, str) and state.upper() == "OPEN"


def read_queue(
    pages: Sequence[Mapping[str, Any]],
    *,
    approval_label: str = APPROVAL_LABEL,
    error: str | None = None,
) -> QueueRead:
    """Build a queue read from one or more raw list-issues payloads.

    ``error`` short-circuits everything: a caller that caught an exception passes it here rather
    than passing an empty page list, so a failure can never arrive shaped like a quiet queue.
    """
    if error:
        return QueueRead.failed(error)
    if not pages:
        return QueueRead.failed("no response was captured from the approved-work query")

    issues: list[QueueIssue] = []
    for index, page in enumerate(pages):
        if page.get("error"):
            return QueueRead.failed(str(page["error"]))

        page_info = page.get("pageInfo") or {}
        has_next = bool(page_info.get("hasNextPage"))
        if has_next and index == len(pages) - 1:
            return QueueRead.failed(
                "the approved-work query returned a partial result: hasNextPage is true and no "
                "further page was supplied, so the queue depth is unknown"
            )

        for raw in page.get("issues") or ():
            if not _is_open(raw) or approval_label not in _labels(raw):
                continue
            number = raw.get("number")
            if not isinstance(number, int):
                return QueueRead.failed(f"an issue in the response has no usable number: {raw!r}")
            issues.append(
                QueueIssue(
                    number=number,
                    title=str(raw.get("title") or ""),
                    body=str(raw.get("body") or ""),
                )
            )

    return QueueRead.ok(issues)


def read_pull_requests(
    payload: Iterable[Mapping[str, Any]],
    *,
    work_id: str,
) -> tuple[LinkedPullRequest, ...]:
    """Open pull requests belonging to this work item.

    Belonging is decided by the work id found in the branch name or the title, never by
    position in the list. The head SHA is kept whole: a revision instruction is matched against
    it, and an abbreviation is a prefix, not an identity.
    """
    linked: list[LinkedPullRequest] = []
    for raw in payload:
        state = str(raw.get("state") or "open")
        if state.lower() != "open":
            continue
        head = raw.get("head") or {}
        ref = str(head.get("ref") or "")
        sha = str(head.get("sha") or "")
        title = str(raw.get("title") or "")
        number = raw.get("number")
        if not isinstance(number, int):
            continue
        if work_id not in ref and work_id.lower() not in title.lower():
            continue
        linked.append(LinkedPullRequest(number=number, work_id=work_id, head_sha=sha))
    return tuple(linked)


def issue_work_id(issue: QueueIssue) -> str | None:
    """The work id the issue itself declares, which is the only authoritative one."""
    return extract_work_id(issue.body)
