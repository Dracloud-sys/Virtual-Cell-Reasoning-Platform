"""The allowed and forbidden paths, enforced rather than remembered.

The policy has no judgement in it on purpose. It compares paths and reports the ones the issue
did not authorise, so the decision to widen a change stays with whoever writes the issue. Four
rules carry the weight:

* **forbidden beats allowed.** A broad allow entry must not quietly reopen a closed door, so
  ``allowed=src/`` with ``forbidden=src/virtualcell/`` still refuses the vertical.
* **the kernel is forbidden unless authorised**, whatever the issue's own lists say. An author
  who writes a wide allow rule and forgets to list the kernel has not authorised a kernel
  change; authorisation is a tick in its own section, and this rule is what makes forgetting
  safe. The implicit guard is dropped only when that box says *Authorized*.
* **a path that is not repository-relative is refused before it is matched.** ``../`` and
  absolute paths escape the tree the rules describe, so they can never be compared honestly -
  ``../../etc/passwd`` starts with no allowed prefix, but neither does anything else, and a
  policy that answers "outside the allow list" to a traversal has answered the wrong question.
* **an empty allow list permits nothing.** A policy that failed to parse has to fail closed;
  the alternative is that a malformed issue reads as unrestricted access.

A rename is two paths, and both are checked. Moving a kernel file out of the kernel is a kernel
change, and it is invisible to anything that only looks at where the file landed.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable
from dataclasses import dataclass

from .outcomes import Outcome, Status
from .spec_contract import split_sections

#: Guarded unless the issue's kernel box says otherwise. Mirrors CLAUDE.md's first invariant.
KERNEL_PATH = "src/virtualcell/reasoning/kernel/"


def _matches(path: str, rule: str) -> bool:
    """A rule ending in ``/`` is a directory prefix; anything else is one exact file."""
    return path.startswith(rule) if rule.endswith("/") else path == rule


def unsafe_reason(path: str) -> str | None:
    """Why this path cannot be judged at all, or None when it is a plain relative path."""
    if not path or path.strip() != path:
        return "empty or padded with whitespace"
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return "absolute"
    if "\\" in path:
        return "uses backslashes; repository paths are posix-style"
    parts = path.split("/")
    if any(part == ".." for part in parts):
        return "escapes the repository with '..'"
    normalised = posixpath.normpath(path)
    if normalised != path.rstrip("/") and normalised + "/" != path:
        return f"is not normalised (would resolve to {normalised!r})"
    return None


@dataclass(frozen=True)
class PathChange:
    """One changed path. A rename carries where it came from as well as where it went."""

    path: str
    previous_path: str | None = None

    def touched(self) -> tuple[str, ...]:
        return (self.path,) if self.previous_path is None else (self.previous_path, self.path)


def as_changes(paths: Iterable[str | PathChange]) -> tuple[PathChange, ...]:
    return tuple(p if isinstance(p, PathChange) else PathChange(p) for p in paths)


@dataclass(frozen=True)
class PathPolicy:
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]
    #: False keeps the kernel guarded no matter what `allowed` and `forbidden` say.
    kernel_authorized: bool = False

    @property
    def effective_forbidden(self) -> tuple[str, ...]:
        if self.kernel_authorized or KERNEL_PATH in self.forbidden:
            return self.forbidden
        return (*self.forbidden, KERNEL_PATH)

    def permits(self, path: str) -> bool:
        if unsafe_reason(path) is not None:
            return False
        if any(_matches(path, rule) for rule in self.effective_forbidden):
            return False
        return any(_matches(path, rule) for rule in self.allowed)

    def verdict(self, changed: Iterable[str | PathChange]) -> Outcome:
        offences: list[str] = []
        for change in as_changes(changed):
            for path in change.touched():
                reason = unsafe_reason(path)
                if reason is not None:
                    offences.append(f"{path} ({reason})")
                elif not self.permits(path):
                    where = " (renamed from)" if path == change.previous_path else ""
                    offences.append(f"{path}{where}")
        if offences:
            joined = ", ".join(dict.fromkeys(offences))
            return Outcome(
                Status.BLOCKED_SCOPE,
                "outside the paths this issue authorises: " + joined,
                {"offending_paths": joined},
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


def parse_path_policy(body: str, *, kernel_authorized: bool = False) -> PathPolicy:
    """Read the two path sections out of an issue body."""
    sections = split_sections(body)
    return PathPolicy(
        allowed=_rules(sections.get("Allowed paths", "")),
        forbidden=_rules(sections.get("Forbidden paths", "")),
        kernel_authorized=kernel_authorized,
    )
