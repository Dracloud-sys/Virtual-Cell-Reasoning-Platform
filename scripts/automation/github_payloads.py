"""Turning what GitHub actually returns into the facts the gate decides from.

The gate is pure, so something has to read real responses, and this is it. It is separate from
`preflight` because parsing is where the interesting mistakes live, and they are all the same
mistake in different clothes: **treating a partial or failed answer as a complete one.**

Four of them are handled explicitly.

* **An error is not an empty list.** Both shapes count: an `error` key, and GitHub's own REST
  error envelope, which carries `message` and `status` and *no* collection at all::

      {"message": "Bad credentials", "status": "401"}

  The previous version looked for `issues`, found nothing, and reported a healthy empty queue.
  A response that does not carry the collection it was asked for is a failed read, full stop.
* **A page is not the queue.** If the response says another page exists and no further page was
  supplied, the read is *incomplete* — and an incomplete read that happens to show one issue
  would send a run off to implement it while a second approved issue sat on page two.
* **A closed issue carrying the label is not queued.** The filter is applied here rather than
  trusted from the caller's query arguments, because a caller that forgot `state=OPEN` would
  otherwise dispatch work from a closed issue.
* **A field that is present but the wrong type is not a value.** `state` missing, `labels` not a
  list, `number` a string: each fails the read rather than being coerced into something usable.

The fixtures in ``tests/automation/fixtures/github/`` are captured from the real tool this
repository's runs use, so the schema below is checked against what actually arrives rather than
against what would be convenient.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .preflight import LinkedPullRequest
from .queue import QueueIssue, QueueRead
from .spec_contract import extract_work_id

#: The label a person applies when they approve an issue for an unattended run.
APPROVAL_LABEL = "claude-ready"


class SchemaError(ValueError):
    """A response that cannot be read as the thing it was supposed to be."""


def _envelope_error(page: Mapping[str, Any]) -> str | None:
    """GitHub's error shapes, and anything else that is plainly not a listing."""
    if page.get("error"):
        return str(page["error"])
    if page.get("errors"):
        return f"errors: {page['errors']!r}"
    if "message" in page and "issues" not in page:
        status = page.get("status") or page.get("documentation_url") or ""
        return f"{page['message']}{f' (status {status})' if status else ''}"
    status = str(page.get("status") or "")
    if status and not status.startswith("2") and status.isdigit():
        return f"HTTP status {status}"
    return None


def _issues_of(page: Mapping[str, Any], index: int) -> Sequence[Any]:
    if "issues" not in page:
        raise SchemaError(f"page {index} carries no 'issues' collection: {sorted(page)!r}")
    issues = page["issues"]
    if not isinstance(issues, list):
        raise SchemaError(f"page {index} has 'issues' of type {type(issues).__name__}, not a list")
    return issues


def _labels(issue: Mapping[str, Any]) -> set[str]:
    """Labels arrive either as strings or as objects with a name, depending on the endpoint."""
    raw = issue.get("labels")
    if raw is None:
        raise SchemaError("an issue carries no 'labels' field")
    if not isinstance(raw, list):
        raise SchemaError(f"'labels' is {type(raw).__name__}, not a list")
    out: set[str] = set()
    for label in raw:
        if isinstance(label, str):
            out.add(label)
        elif isinstance(label, Mapping) and isinstance(label.get("name"), str):
            out.add(label["name"])
        else:
            raise SchemaError(f"unreadable label entry: {label!r}")
    return out


def _is_open(issue: Mapping[str, Any]) -> bool:
    state = issue.get("state")
    if not isinstance(state, str):
        raise SchemaError("an issue carries no readable 'state'")
    return state.upper() == "OPEN"


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
    try:
        for index, page in enumerate(pages):
            if not isinstance(page, Mapping):
                raise SchemaError(f"page {index} is {type(page).__name__}, not an object")
            envelope = _envelope_error(page)
            if envelope:
                return QueueRead.failed(envelope)

            page_info = page.get("pageInfo") or {}
            if not isinstance(page_info, Mapping):
                raise SchemaError(f"page {index} has an unreadable 'pageInfo'")
            if bool(page_info.get("hasNextPage")) and index == len(pages) - 1:
                return QueueRead.failed(
                    "the approved-work query returned a partial result: hasNextPage is true and "
                    "no further page was supplied, so the queue depth is unknown"
                )

            for raw in _issues_of(page, index):
                if not isinstance(raw, Mapping):
                    raise SchemaError(f"page {index} holds a non-object issue: {raw!r}")
                if not _is_open(raw) or approval_label not in _labels(raw):
                    continue
                number = raw.get("number")
                if not isinstance(number, int) or isinstance(number, bool):
                    raise SchemaError(f"an issue has no usable number: {raw.get('number')!r}")
                issues.append(
                    QueueIssue(
                        number=number,
                        title=str(raw.get("title") or ""),
                        body=str(raw.get("body") or ""),
                    )
                )
    except SchemaError as problem:
        return QueueRead.failed(f"the approved-work response did not parse: {problem}")

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
    if isinstance(payload, Mapping):
        envelope = _envelope_error(payload)
        raise SchemaError(envelope or "the pull request response is an object, not a list")

    linked: list[LinkedPullRequest] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise SchemaError(f"a pull request entry is {type(raw).__name__}, not an object")
        state = str(raw.get("state") or "open")
        if state.lower() != "open":
            continue
        head = raw.get("head") or {}
        if not isinstance(head, Mapping):
            raise SchemaError("a pull request carries an unreadable 'head'")
        ref = str(head.get("ref") or "")
        sha = str(head.get("sha") or "")
        title = str(raw.get("title") or "")
        number = raw.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise SchemaError(f"a pull request has no usable number: {raw.get('number')!r}")
        if work_id not in ref and work_id.lower() not in title.lower():
            continue
        linked.append(LinkedPullRequest(number=number, work_id=work_id, head_sha=sha))
    return tuple(linked)


def issue_work_id(issue: QueueIssue) -> str | None:
    """The work id the issue itself declares, which is the only authoritative one."""
    return extract_work_id(issue.body)
