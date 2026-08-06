"""Domain-independent assertion safety (PR14a).

Some phrasings a report must never *assert*, because asserting them would claim more than
the evidence supports — "P53 loss" where the source said "P53-independent", "causes" where
the graph said "associated with". Which phrasings those are is domain policy. **Where to
look for them is not**, and getting that scope wrong is a bug in both directions.

The rule, learned the hard way in PR10b: a forbidden-phrase check must scan only the
fields that make an assertion — the conclusion and the evidence claims, where a narrative
layer would later land. It must **not** scan the safety-guidance fields, because those
name the forbidden phrases in order to prohibit them. "P53-independent does not mean P53
loss" is correct guidance; a scanner that flags it has punished the report for being
careful. Graph path strings are excluded for the same reason — a path legitimately
contains the entity names a phrase is built from.

Encoding that scope once, here, is the point. A second vertical re-deriving "what counts
as an assertion" would eventually derive it differently, and the difference would show up
as either a false alarm or a claim that got through.
"""

from __future__ import annotations

from collections.abc import Iterable

from virtualcell.reasoning.decision import DecisionReport


class AssertionSafetyError(ValueError):
    """Raised when a report *asserts* a phrasing its domain policy forbids."""


def assertion_texts(report: DecisionReport) -> list[str]:
    """The report fields that make biological *assertions*.

    The conclusion and both sides of the evidence — nothing else. ``limitations``,
    ``overinterpretation_risk``, ``uncertainty`` and the mechanistic path strings are
    excluded by design: they discuss claims rather than making them.
    """
    return [
        report.conclusion,
        *(claim.statement for claim in report.supporting_evidence),
        *(claim.statement for claim in report.contradicting_evidence),
    ]


def forbidden_phrases_in(report: DecisionReport, phrases: Iterable[str]) -> list[str]:
    """Which of ``phrases`` the report actually asserts (case-insensitive; may be empty).

    ``phrases`` is the domain's policy. This function owns only the scope and the match.
    """
    asserted = " ".join(assertion_texts(report)).lower()
    return [phrase for phrase in phrases if phrase.lower() in asserted]


def validate_assertions(
    report: DecisionReport,
    phrases: Iterable[str],
    *,
    error: type[AssertionSafetyError] = AssertionSafetyError,
    context: str = "report",
) -> None:
    """Raise unless the report asserts none of ``phrases``.

    A pack may pass its own error type so a safety failure stays attributable to the
    domain whose policy was violated.
    """
    for phrase in forbidden_phrases_in(report, phrases):
        raise error(f"forbidden phrasing in {context}: {phrase!r}")
