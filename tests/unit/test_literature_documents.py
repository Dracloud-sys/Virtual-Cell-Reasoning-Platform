"""Tests for safe open-access JATS parsing (PR8c-1). No network."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from virtualcell.literature.contracts import ArticleIdentifier, ArticleRecord
from virtualcell.literature.documents import (
    JatsLimits,
    JatsParseError,
    content_hash,
    document_from_abstract,
    parse_jats,
)

_ARTICLE = ArticleIdentifier(pmcid="PMC1", pmid="1")

JATS = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta>
    <abstract><p>TERT expression <italic>increased</italic> after long-term culture.</p></abstract>
    <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/">
      <license-p>CC BY 4.0</license-p></license></permissions>
  </article-meta></front>
  <body>
    <sec id="s1"><title>Results</title>
      <p>Cells at <italic>passage 35</italic> showed 2.4-fold TERT.</p></sec>
    <sec id="s2"><title>Discussion</title><p>Cells escaped senescence.</p></sec>
  </body>
  <back>
    <table-wrap id="T1">
      <caption><p>Marker levels</p></caption>
      <table>
        <thead><tr><th>Marker</th><th>P3</th><th>P35</th></tr></thead>
        <tbody>
          <tr><td>TERT</td><td>1.0</td><td>2.4</td></tr>
          <tr><td>CDK4</td><td>1.0</td><td>1.1 &#177; 0.2</td></tr>
          <tr><td>SA_b_gal</td><td>low</td><td>increased</td></tr>
        </tbody>
      </table>
      <table-wrap-foot><p>Values are fold change vs P3.</p></table-wrap-foot>
    </table-wrap>
  </back>
</article>
"""


def _doc(**kw):
    return parse_jats(JATS, article=_ARTICLE, provider="europe_pmc", **kw)


def test_parses_abstract_sections_and_license() -> None:
    doc = _doc()
    assert "TERT expression increased" in doc.abstract  # inline <italic> text preserved
    assert [s.section_id for s in doc.sections] == ["s1", "s2"]  # original order
    assert doc.sections[0].title == "Results"
    assert "passage 35" in doc.sections[0].text  # inline tag text not lost
    assert doc.license == "https://creativecommons.org/licenses/by/4.0/"
    assert doc.source_format.value == "jats_xml"


def test_parses_table_structure() -> None:
    table = _doc().tables[0]
    assert table.table_id == "T1"
    assert table.caption == "Marker levels"
    assert table.headers == ["Marker", "P3", "P35"]
    assert table.footnotes == ["Values are fold change vs P3."]
    cell = table.cell(0, 2)
    assert cell.text == "2.4"
    assert cell.row_label == "TERT"
    assert cell.column_label == "P35"


def test_content_hash_detects_source_drift() -> None:
    doc = _doc()
    assert doc.content_hash == content_hash(JATS)
    assert content_hash(JATS) != content_hash(JATS + " ")


def test_metadata_carries_no_body_text() -> None:
    meta = _doc().metadata()
    dumped = meta.model_dump(mode="json")
    assert meta.section_count == 2 and meta.table_count == 1
    # The full text must never travel in the bundle.
    assert "escaped senescence" not in str(dumped)
    assert meta.content_hash == content_hash(JATS)


def test_entity_declarations_are_refused() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE r [ <!ENTITY lol "lol"> ]><r>&lol;</r>'
    with pytest.raises(JatsParseError):
        parse_jats(bomb, article=_ARTICLE)


def test_oversized_xml_is_rejected() -> None:
    with pytest.raises(JatsParseError, match="byte limit"):
        parse_jats(JATS, article=_ARTICLE, limits=JatsLimits(max_bytes=10))


def test_malformed_xml_is_a_typed_error() -> None:
    with pytest.raises(JatsParseError, match="malformed"):
        parse_jats("<article><body>", article=_ARTICLE)


def test_missing_body_is_a_warning_not_an_error() -> None:
    xml = (
        "<article><front><article-meta>"
        "<abstract><p>A</p></abstract>"
        "</article-meta></front></article>"
    )
    doc = parse_jats(xml, article=_ARTICLE)
    assert doc.sections == []
    assert any("no <body>" in w for w in doc.warnings)
    assert doc.abstract == "A"  # a body-less document is still usable


def test_section_and_table_limits_truncate_with_a_warning() -> None:
    doc = parse_jats(JATS, article=_ARTICLE, limits=JatsLimits(max_sections=1))
    assert len(doc.sections) == 1
    assert any("truncated at 1 sections" in w for w in doc.warnings)


def test_abstract_only_fallback_document() -> None:
    record = ArticleRecord(
        identifiers=_ARTICLE,
        abstract="Only an abstract.",
        provider="europe_pmc",
        retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    doc = document_from_abstract(record)
    assert doc.source_format.value == "abstract"
    assert doc.sections == [] and doc.tables == []
    assert doc.content_hash == content_hash("Only an abstract.")
