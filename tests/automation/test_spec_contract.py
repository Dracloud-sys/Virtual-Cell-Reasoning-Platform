"""Question 3: a spec that is not a contract must stop the run, not be interpreted.

The failure this guards is quiet. A template section left as its instructional comment reads,
to anything scanning for text, as a section that is present. "Forbidden paths" left blank does
not mean the author had nothing to add; it means nothing is forbidden, which is the opposite
of what an unfilled template intends. So an empty section is a refusal, and "does not apply"
has to be written down as `none` or `N/A` *with the reason*, which is a thing a person can
disagree with in review.
"""

from __future__ import annotations

import pytest
from automation.spec_contract import REQUIRED_SECTIONS, validate_spec

COMPLETE = """## Work ID

`vcrp-ops-001`

## Goal

Prove the contract holds.

## Work type

- [x] Implementation
- [ ] Investigation-first

## Pre-implementation verification questions

- Does the gate refuse an empty queue?

## Allowed paths

```
scripts/automation/
```

## Forbidden paths

```
src/virtualcell/
```

## Kernel authorization

- [x] Not authorized
- [ ] Authorized

## Non-goals

No product behaviour changes.

## Stop conditions

A scientific judgement is required.

## Acceptance criteria

- The questions pass.

## Biological content change intent

- [x] No biological content changes intended
- [ ] Changes intended

## Interface impact

none - nothing reaches the API, CLI or MCP surface.
"""


def _without(section: str) -> str:
    """Drop one whole section, heading included."""
    blocks = COMPLETE.split("## ")
    return "## ".join(b for b in blocks if not b.startswith(section))


def _replace_body(section: str, new_body: str) -> str:
    blocks = COMPLETE.split("## ")
    out = []
    for block in blocks:
        if block.startswith(section):
            out.append(f"{section}\n\n{new_body}\n\n")
        else:
            out.append(block)
    return "## ".join(out)


def test_a_complete_spec_is_accepted() -> None:
    report = validate_spec(COMPLETE)

    assert report.ok, report.problems


@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_every_required_section_is_required(section: str) -> None:
    report = validate_spec(_without(section))

    assert not report.ok
    assert any(section in problem for problem in report.problems)


def test_a_section_left_as_its_instructional_comment_is_not_filled_in() -> None:
    body = _replace_body("Non-goals", "<!-- what this deliberately does not do -->")
    report = validate_spec(body)

    assert not report.ok
    assert any("Non-goals" in p for p in report.problems)


def test_an_empty_forbidden_paths_section_is_refused() -> None:
    """Blank here reads as 'nothing is forbidden'. That has to be said on purpose."""
    report = validate_spec(_replace_body("Forbidden paths", ""))

    assert not report.ok
    assert any("Forbidden paths" in p for p in report.problems)


def test_none_without_a_reason_is_refused() -> None:
    report = validate_spec(_replace_body("Interface impact", "none"))

    assert not report.ok
    assert any("Interface impact" in p and "reason" in p for p in report.problems)


def test_none_with_a_reason_is_accepted() -> None:
    body = _replace_body("Interface impact", "none - the gate is not a product surface.")
    report = validate_spec(body)

    assert report.ok, report.problems


def test_two_boxes_checked_in_one_choice_is_a_contradiction() -> None:
    body = _replace_body(
        "Kernel authorization",
        "- [x] Not authorized\n- [x] Authorized",
    )
    report = validate_spec(body)

    assert not report.ok
    assert any("Kernel authorization" in p and "both" in p for p in report.problems)


def test_no_box_checked_in_one_choice_is_undecided() -> None:
    body = _replace_body(
        "Work type",
        "- [ ] Implementation\n- [ ] Investigation-first",
    )
    report = validate_spec(body)

    assert not report.ok
    assert any("Work type" in p for p in report.problems)


def test_kernel_authorization_defaults_closed_and_must_be_stated() -> None:
    """No silent authorisation: the box has to be ticked by a person, either way."""
    body = _replace_body("Kernel authorization", "we probably will not need it")
    report = validate_spec(body)

    assert not report.ok
    assert any("Kernel authorization" in p for p in report.problems)


def test_problems_name_every_bad_section_not_only_the_first() -> None:
    body = _replace_body("Non-goals", "")
    body = body.replace("- [x] Implementation", "- [ ] Implementation")
    report = validate_spec(body)

    assert len(report.problems) >= 2
