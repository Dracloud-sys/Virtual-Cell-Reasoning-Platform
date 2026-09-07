"""Whether an issue is a contract or just a filled-in-looking form.

The template's sections are the terms a run executes against, so the check is not "are the
headings there" but "did a person put a decision under each one". Four failure shapes are
treated as equivalent to a missing section, because they are equally unsafe to act on:

* an empty section - blank *Forbidden paths* reads as "nothing is forbidden";
* a section still holding its instructional HTML comment - present to a scanner, unwritten
  to a reader;
* a bare ``none`` with no reason - indistinguishable from a section nobody thought about;
* a placeholder - ``TODO``, ``TBD``, ``<reason>``. These are the most dangerous of the four,
  because they are *evidence someone opened the section and did not finish it*, and they read
  as content to anything checking for non-emptiness.

A choice section has one more rule: exactly one box ticked. Zero is undecided, both is a
contradiction, and neither may be resolved by picking the safer-looking one - guessing is how
an unauthorised kernel change acquires its authorisation.

Two choices have consequences beyond the tick, and both are checked here rather than trusted:
authorising a kernel change requires naming the paths and the reason, and declaring a
biological content change requires stating the change and its grounding. A tick with nothing
under it authorises everything and specifies nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

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
_CHECKED = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*(?P<label>.*)$", re.MULTILINE)
_UNCHECKED = re.compile(r"^\s*[-*]\s*\[\s*\]", re.MULTILINE)
_BARE_NONE = re.compile(r"^[`\s]*(none|n/?a)[.\s`]*$", re.IGNORECASE)
_WORK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")

#: Unfinished markers. `<...>` catches the template's own `<reason>` shape; the words catch the
#: human ones. Matched on the cleaned prose, so a mention inside an HTML comment does not count.
_PLACEHOLDERS = re.compile(
    r"(?<![A-Za-z0-9])(TODO|TBD|FIXME|XXX|\?\?\?)(?![A-Za-z0-9])|<[a-z_ ]{2,30}>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpecReport:
    """Everything wrong with a spec, not merely the first thing wrong with it."""

    problems: tuple[str, ...]
    work_id: str | None = None
    kernel_authorized: bool = False
    biological_changes_intended: bool = False
    selections: Mapping[str, str] = field(default_factory=dict)

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


def _checked_labels(text: str) -> list[str]:
    return [match.group("label").strip() for match in _CHECKED.finditer(_COMMENT.sub("", text))]


def extract_work_id(body: str) -> str | None:
    """The slug the issue declares, or None when it does not declare a usable one."""
    section = split_sections(body).get("Work ID")
    if section is None:
        return None
    candidate = _prose(section).strip().strip("`").strip()
    first = candidate.splitlines()[0].strip().strip("`").strip() if candidate else ""
    return first if _WORK_ID.match(first) else None


def _choice_problem(name: str, text: str) -> str | None:
    checked = len(_checked_labels(text))
    if checked == 0:
        return f"{name}: no option is selected; the choice has to be made explicitly."
    if checked > 1:
        return f"{name}: both options are checked; exactly one must be selected."
    return None


def _selected_label(text: str) -> str:
    """The one ticked option, normalised. Empty when none or more than one is ticked."""
    labels = _checked_labels(text)
    if len(labels) != 1:
        return ""
    return labels[0].replace("*", "").replace("`", "").strip().lower()


def _is_negative(label: str, *negatives: str) -> bool:
    """Whether the ticked option is the closed one.

    Checked negative-first on purpose. "No biological content changes intended" *contains*
    "changes intended", and "Not authorized" contains "authorized", so a positive substring
    test reads every closed choice as an open one — which is the direction that matters, since
    the open ones are what permit a kernel or a claim to move.
    """
    return any(negative in label for negative in negatives)


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
        else:
            found = _PLACEHOLDERS.search(prose)
            if found:
                problems.append(
                    f"{name}: still holds the placeholder {found.group(0)!r}; an unfinished "
                    "section is not a decision."
                )

    kernel_text = sections.get("Kernel authorization", "")
    kernel_label = _selected_label(kernel_text)
    kernel_authorized = bool(kernel_label) and not _is_negative(kernel_label, "not authorized")
    if kernel_authorized and len(_prose(kernel_text)) < 20:
        problems.append(
            "Kernel authorization: authorised without naming the files and the reason the "
            "change cannot live in a caller."
        )

    bio_text = sections.get("Biological content change intent", "")
    bio_label = _selected_label(bio_text)
    bio_intended = bool(bio_label) and not _is_negative(bio_label, "no biological", "no changes")
    if bio_intended and len(_prose(bio_text)) < 20:
        problems.append(
            "Biological content change intent: changes are declared but not specified; state "
            "the change and its literature grounding."
        )

    work_id = extract_work_id(body)
    if (
        "Work ID" in sections
        and work_id is None
        and not any(p.startswith("Work ID") for p in problems)
    ):
        problems.append("Work ID: not a usable slug; expected kebab-case such as `vcrp-ops-002`.")

    return SpecReport(
        problems=tuple(problems),
        work_id=work_id,
        kernel_authorized=kernel_authorized,
        biological_changes_intended=bio_intended,
    )
