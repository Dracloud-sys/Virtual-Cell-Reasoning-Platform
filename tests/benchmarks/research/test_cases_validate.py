"""The development cases must stay loadable as the contract moves.

They exist to be run in P4, which is later; a contract change between now and then would
otherwise break them silently and be discovered when someone finally tried to use them.
This is a shape check only — it runs no model and says nothing about the designs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from virtualcell.research import ResearchRequest

CASES = sorted((Path(__file__).parent / "cases").glob("*.json"))

#: Carries a deliberately fake DOI so no fabricated citation enters a file about citations.
#: Listed, not runnable, until a real read span replaces it.
PLACEHOLDER_CASES = {"species_mismatch.json"}


def test_there_are_cases_to_run() -> None:
    assert CASES, "no development cases found"


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_each_case_validates_against_the_contract(path: Path) -> None:
    request = ResearchRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    assert request.question
    assert request.evidence, "a case with no evidence tests nothing about evidence handling"


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_a_placeholder_source_says_so_in_its_own_text(path: Path) -> None:
    """A fake DOI is acceptable only while the span it carries announces itself as fake."""
    request = ResearchRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    for item in request.evidence:
        if item.locator is None:
            continue
        doi = (item.locator.article.doi or "").lower()
        if "placeholder" in doi:
            assert path.name in PLACEHOLDER_CASES
            assert "PLACEHOLDER" in item.locator.source_text
