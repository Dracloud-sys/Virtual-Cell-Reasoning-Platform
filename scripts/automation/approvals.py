"""Deriving an approval from the record, rather than believing a field that says "approved".

The previous round accepted a `RevisionInstruction` the calling agent had already assembled:
`approved_by` and `approval_record_id` were strings in the request file, and the gate checked
that they were non-empty. That is a check on the agent's typing, not on GitHub's records — the
agent writes the request, so it could write any name into it.

So the parser starts from the raw review or comment payload and derives every field itself:

* the **immutable record id** GitHub assigned;
* the **author login** GitHub recorded, which is the only thing an allow-list can be checked
  against;
* the **body**, which is the instruction and is kept verbatim;
* the **pull request** it was left on;
* the **full head SHA** the instruction is bound to, taken from the review's `commit_id` — the
  commit GitHub says the reviewer was looking at, not one the agent supplies alongside.

Two fail-closed rules, both of them cases where the permissive reading is silently dangerous:

* **an empty approver list approves nobody.** Read as "no restriction", it turns a missing
  configuration into universal authority.
* **a payload that does not carry all five fields is not an approval.** A partial record cannot
  be audited later, and "we could not tell who approved it" is not a state a run may proceed
  from.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .revisions import RevisionInstruction

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

#: Committed, reviewable, and outside the request file the agent writes.
DEFAULT_APPROVERS_FILE = "docs/operations/run_approvers.json"


class ApproverConfigError(RuntimeError):
    """The approver list is missing, unreadable, or empty. Never a reason to allow everyone."""


def load_approvers(path: Path) -> tuple[str, ...]:
    """The logins allowed to approve a revision, from a committed file.

    Raises rather than returning an empty tuple. An empty allow-list is a configuration error,
    and the one behaviour it must never produce is "everyone is an approver".
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ApproverConfigError(f"no approver list at {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ApproverConfigError(f"approver list at {path} is unreadable: {error}") from error

    approvers = raw.get("approvers") if isinstance(raw, Mapping) else raw
    if not isinstance(approvers, list) or not all(isinstance(name, str) for name in approvers):
        raise ApproverConfigError(f"approver list at {path} is not a list of logins")
    cleaned = tuple(name.strip() for name in approvers if name.strip())
    if not cleaned:
        raise ApproverConfigError(f"approver list at {path} is empty; that approves nobody")
    return cleaned


@dataclass(frozen=True)
class ApprovalProblem:
    """One payload that was not accepted, and the reason. Reported, never silently dropped."""

    where: str
    reason: str

    def __str__(self) -> str:
        return f"{self.where}: {self.reason}"


def _first(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload and payload[name] not in (None, ""):
            return payload[name]
    return None


def parse_approvals(
    payloads: Iterable[Mapping[str, Any]],
    *,
    approvers: Sequence[str],
) -> tuple[tuple[RevisionInstruction, ...], tuple[ApprovalProblem, ...]]:
    """Turn raw review/comment payloads into instructions, and say why the rest were refused."""
    if not approvers:
        raise ApproverConfigError("no approvers are configured; that approves nobody")

    accepted: list[RevisionInstruction] = []
    problems: list[ApprovalProblem] = []

    for index, payload in enumerate(payloads):
        where = f"approval[{index}]"
        record_id = _first(payload, "id", "node_id")
        user = payload.get("user") if isinstance(payload.get("user"), Mapping) else {}
        login = _first(user or {}, "login")
        body = _first(payload, "body")
        commit = _first(payload, "commit_id", "commit_sha")
        pull_request = _first(payload, "pull_request_number", "number")
        if pull_request is None:
            url = str(_first(payload, "pull_request_url", "html_url") or "")
            match = re.search(r"/pulls?/(\d+)", url)
            pull_request = int(match.group(1)) if match else None
        state = str(_first(payload, "state") or "").upper()

        if record_id is None:
            problems.append(ApprovalProblem(where, "carries no immutable record id"))
            continue
        if not login:
            problems.append(ApprovalProblem(where, "GitHub recorded no author login"))
            continue
        if login not in approvers:
            problems.append(ApprovalProblem(where, f"{login!r} is not an accepted approver"))
            continue
        if not body:
            problems.append(ApprovalProblem(where, "has no body, so there is no instruction"))
            continue
        if not isinstance(pull_request, int):
            problems.append(ApprovalProblem(where, "names no pull request"))
            continue
        if not (isinstance(commit, str) and _FULL_SHA.match(commit.lower())):
            problems.append(
                ApprovalProblem(where, "GitHub recorded no full commit id for the instruction")
            )
            continue
        if state and state not in {"APPROVED", "COMMENTED"}:
            problems.append(ApprovalProblem(where, f"review state is {state}, not an approval"))
            continue

        accepted.append(
            RevisionInstruction(
                identifier=str(record_id),
                approved_by=str(login),
                target_pull_request=pull_request,
                target_head_sha=str(commit).lower(),
                approval_record_id=str(record_id),
                content=str(body),
            )
        )

    return tuple(accepted), tuple(problems)
