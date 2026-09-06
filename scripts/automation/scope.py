"""The allowed and forbidden paths, enforced rather than remembered.

The policy has no judgement in it on purpose. It compares paths and reports the ones the issue
did not authorise, so the decision to widen a change stays with whoever writes the issue. Two
rules carry the weight:

* **forbidden beats allowed.** A broad allow entry must not quietly reopen a closed door, so
  ``allowed=src/`` with ``forbidden=src/virtualcell/`` still refuses the vertical.
* **an empty allow list permits nothing.** A policy that failed to parse has to fail closed;
  the alternative is that a malformed issue reads as unrestricted access.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .outcomes import Outcome, Status
from .spec_contract import split_sections


def _matches(path: str, rule: str) -> bool:
    """A rule ending in ``/`` is a directory prefix; anything else is one exact file."""
    return path.startswith(rule) if rule.endswith("/") else path == rule


@dataclass(frozen=True)
class PathPolicy:
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]

    def permits(self, path: str) -> bool:
        if any(_matches(path, rule) for rule in self.forbidden):
            return False
        return any(_matches(path, rule) for rule in self.allowed)

    def verdict(self, changed_paths: Iterable[str]) -> Outcome:
        offenders = tuple(path for path in changed_paths if not self.permits(path))
        if offenders:
            return Outcome(
                Status.BLOCKED_SCOPE,
                "outside the paths this issue authorises: " + ", ".join(offenders),
                {"offending_paths": ", ".join(offenders)},
            )
        return Outcome(Status.READY_TO_IMPLEMENT, "every changed path is authorised")


def _rules(text: str) -> tuple[str, ...]:
    rules = []
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        if not line or line.startswith(("```", "<!--", "#", "-")):
            continue
        rules.append(line)
    return tuple(rules)


def parse_path_policy(body: str) -> PathPolicy:
    """Read the two path sections out of an issue body."""
    sections = split_sections(body)
    return PathPolicy(
        allowed=_rules(sections.get("Allowed paths", "")),
        forbidden=_rules(sections.get("Forbidden paths", "")),
    )
