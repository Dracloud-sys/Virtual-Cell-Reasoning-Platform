"""Shared pytest fixtures.

Fixtures live here rather than being imported from one test module into another: a
cross-module ``from tests.unit.test_x import Y`` only resolves when the rootdir
happens to be importable, so collection breaks in a clean environment (``No module
named 'tests'``). pytest loads conftest without any package import, and the sample
document is read from a data file by path — both are portable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from virtualcell.literature.contracts import ArticleIdentifier

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def jats_xml() -> str:
    """A small open-access JATS sample: abstract, two sections, one structured table."""
    return (_FIXTURES / "sample_jats.xml").read_text(encoding="utf-8")


@pytest.fixture
def article_identifier() -> ArticleIdentifier:
    """The identifier the JATS sample belongs to."""
    return ArticleIdentifier(pmcid="PMC1", pmid="1", provider_id="PMC1")
