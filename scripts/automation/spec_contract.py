"""Whether an issue is a contract or just a filled-in-looking form.

The template's sections are the terms a run executes against, so the check is not "are the
headings there" but "did a person put a decision under each one". Three failure shapes are
treated as equivalent to a missing section, because they are equally unsafe to act on:

* an empty section - blank *Forbidden paths* reads as "nothing is forbidden";
* a section still holding its instructional HTML comment - present to a scanner, unwritten
  to a reader;
* a bare ``none`` with no reason - indistinguishable from a section nobody thought about.

A choice section (work type, kernel authorisation, biological intent) has one more rule: the
box has to be ticked, and only one of them. Zero ticked is undecided; both ticked is a
contradiction, and neither may be resolved by picking the safer-looking one, because guessing
is how an unauthorised kernel change gets its authorisation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Work ID",
    "Goal",
    "Work type",
    "Pre-implementation verification questions",
    "Allowed paths",
    "Forbidden paths",
    "Kernel authorization",
    "Non-goals",
    "Stop conditions",
    "Acceptance criteria",
    "Biological content change intent",
    "Interface impact",
)

#: Sections where exactly one box must be ticked.
CHOICE_SECTIONS: frozenset[str] = frozenset(
    {"Work type", "Kernel authorization", "Biological content change intent"}
)

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CHECKED = re.compile(r"^\s*[-*]\s*\[[xX]\]", re.MULTILINE)
_UNCHECKED = re.compile(r"^\s*[-*]\s*\[\s*\]", re.MULTILINE)
_BARE_NONE = re.compile(r"^[`\s]*(none|n/?a)[.\s`]*$", re.IGNORECASE)


@dataclass(frozen=True)
class SpecReport:
    """Everything wrong with a spec, not merely the first thing wrong with it."""

    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def split_sections(body: str) -> dict[str, str]:
    """Map ``## Heading`` to the text under it, in document order."""
    sections: dict[str, str] = {}
    heading: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections[heading] = "\n".join(buffer)
            heading = line[3:].strip()
            buffer = []
        elif heading is not None:
            buffer.append(line)
    if heading is not None:
        sections[heading] = "\n".join(buffer)
    return sections


def _prose(text: str) -> str:
    """The section with its scaffolding removed: comments, fences and checkbox lines."""
    without_comments = _COMMENT.sub("", text)
    kept = [
        line
        for line in without_comments.splitlines()
        if not line.strip().startswith("```")
        and not _CHECKED.match(line)
        and not _UNCHECKED.match(line)
    ]
    return "\n".join(kept).strip()


def _choice_problem(name: str, text: str) -> str | None:
    checked = len(_CHECKED.findall(text))
    if checked == 0:
        return f"{name}: no option is selected; the choice has to be made explicitly."
    if checked > 1:
        return f"{name}: both options are checked; exactly one must be selected."
    return None


def validate_spec(body: str) -> SpecReport:
    """Every reason this issue cannot be executed as written."""
    sections = split_sections(body)
    problems: list[str] = []

    for name in REQUIRED_SECTIONS:
        if name not in sections:
            problems.append(f"{name}: section is missing.")
            continue

        text = sections[name]
        if name in CHOICE_SECTIONS:
            problem = _choice_problem(name, text)
            if problem:
                problems.append(problem)
            continue

        prose = _prose(text)
        if not prose:
            problems.append(f"{name}: empty, or still holding its template comment.")
        elif _BARE_NONE.match(prose):
            problems.append(
                f"{name}: states none without a reason; write `none - <reason>` instead."
            )

    return SpecReport(problems=tuple(problems))
