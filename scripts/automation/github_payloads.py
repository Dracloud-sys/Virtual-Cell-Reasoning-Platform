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
* **An empty queue has to be corroborated.** `totalCount` is the listing's own count, so an
  empty queue is believable only when the listing says zero and supplies zero. A payload
  claiming three matching issues while carrying none is not "nothing to do" — it is a read that
  lost something, and reporting `NO_READY_WORK` from it is the quiet failure this whole package
  exists to prevent. There is deliberately no request field for "the queue was empty": the raw
  response is the only way to say it.
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

from .completion import OpenPullRequest
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
    #: The listing's own count, and how many entries actually arrived. An empty queue is only
    #: believable when the two agree at zero.
    declared: int | None = None
    supplied = 0
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

            count = page.get("totalCount")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise SchemaError(
                    f"page {index} carries no usable totalCount: {page.get('totalCount')!r}"
                )
            if declared is None:
                declared = count
            elif declared != count:
                raise SchemaError(
                    f"page {index} says totalCount {count} where an earlier page said {declared}"
                )

            entries = _issues_of(page, index)
            supplied += len(entries)
            for raw in entries:
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

    if declared != supplied:
        return QueueRead.failed(
            f"the approved-work query says {declared} issue(s) match but {supplied} were "
            "supplied; that is an incomplete read, not an empty queue"
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


def read_open_pull_requests(payload: Iterable[Mapping[str, Any]]) -> tuple[OpenPullRequest, ...]:
    """Every open pull request in a raw listing, with the fields completion is judged on.

    Separate from :func:`read_pull_requests`, which answers "is a reviewer already holding this
    work item" and needs only the number and head SHA. Completion asks a different question and
    needs the branch, the base and the draft flag — and refuses a payload that omits `draft`
    rather than guessing, because both guesses are wrong in a way that matters: assuming true
    completes a run that published a ready-for-review pull request, and assuming false refuses
    every correct run.
    """
    if isinstance(payload, Mapping):
        envelope = _envelope_error(payload)
        raise SchemaError(envelope or "the pull request response is an object, not a list")

    pulls: list[OpenPullRequest] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise SchemaError(f"a pull request entry is {type(raw).__name__}, not an object")
        if str(raw.get("state") or "open").lower() != "open":
            continue
        number = raw.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise SchemaError(f"a pull request has no usable number: {raw.get('number')!r}")
        head, base = raw.get("head") or {}, raw.get("base") or {}
        if not isinstance(head, Mapping) or not isinstance(base, Mapping):
            raise SchemaError(f"pull request #{number} carries an unreadable head or base")
        draft = raw.get("draft")
        if not isinstance(draft, bool):
            raise SchemaError(f"pull request #{number} does not report whether it is a draft")
        pulls.append(
            OpenPullRequest(
                number=number,
                head_ref=str(head.get("ref") or ""),
                head_sha=str(head.get("sha") or ""),
                base_ref=str(base.get("ref") or ""),
                draft=draft,
                title=str(raw.get("title") or ""),
            )
        )
    return tuple(pulls)


def issue_work_id(issue: QueueIssue) -> str | None:
    """The work id the issue itself declares, which is the only authoritative one."""
    return extract_work_id(issue.body)
