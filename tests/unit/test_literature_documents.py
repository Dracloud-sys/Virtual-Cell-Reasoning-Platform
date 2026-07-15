"""Tests for safe open-access JATS parsing (PR8c-1). No network.

The JATS sample comes from the ``jats_xml`` conftest fixture (a data file), so no
test module imports another.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from virtualcell.literature.contracts import ArticleRecord, SourceFormat
from virtualcell.literature.documents import (
    ArticleDocument,
    JatsLimits,
    JatsParseError,
    content_hash,
    document_from_abstract,
    parse_jats,
)


@pytest.fixture
def doc(jats_xml, article_identifier):
    return parse_jats(jats_xml, article=article_identifier, provider="europe_pmc")


def test_parses_abstract_sections_and_license(doc) -> None:
    assert "TERT expression increased" in doc.abstract  # inline <italic> text preserved
    assert [s.section_id for s in doc.sections] == ["s1", "s2"]  # original order
    assert doc.sections[0].title == "Results"
    assert "passage 35" in doc.sections[0].text  # inline tag text not lost
    assert doc.license == "https://creativecommons.org/licenses/by/4.0/"
    assert doc.source_format is SourceFormat.JATS_XML


def test_parses_table_structure(doc) -> None:
    table = doc.tables[0]
    assert table.table_id == "T1"
    assert table.caption == "Marker levels"
    assert table.headers == ["Marker", "P3", "P35"]
    assert table.footnotes == ["Values are fold change vs P3."]
    cell = table.cell(0, 2)
    assert cell.text == "2.4"
    assert cell.row_label == "TERT"
    assert cell.column_label == "P35"


def test_content_hash_detects_source_drift(doc, jats_xml) -> None:
    assert doc.content_hash == content_hash(jats_xml)
    assert content_hash(jats_xml) != content_hash(jats_xml + " ")


def test_metadata_carries_no_body_text(doc, jats_xml) -> None:
    meta = doc.metadata()
    assert meta.section_count == 2 and meta.table_count == 1
    # The full text must never travel in the bundle.
    assert "escaped senescence" not in str(meta.model_dump(mode="json"))
    assert meta.content_hash == content_hash(jats_xml)


def test_entity_declarations_are_refused(article_identifier) -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE r [ <!ENTITY lol "lol"> ]><r>&lol;</r>'
    with pytest.raises(JatsParseError):
        parse_jats(bomb, article=article_identifier)


def test_oversized_xml_is_rejected(jats_xml, article_identifier) -> None:
    with pytest.raises(JatsParseError, match="byte limit"):
        parse_jats(jats_xml, article=article_identifier, limits=JatsLimits(max_bytes=10))


def test_malformed_xml_is_a_typed_error(article_identifier) -> None:
    with pytest.raises(JatsParseError, match="malformed"):
        parse_jats("<article><body>", article=article_identifier)


def test_missing_body_is_a_warning_not_an_error(article_identifier) -> None:
    xml = (
        "<article><front><article-meta>"
        "<abstract><p>A</p></abstract>"
        "</article-meta></front></article>"
    )
    doc = parse_jats(xml, article=article_identifier)
    assert doc.sections == []
    assert any("no <body>" in w for w in doc.warnings)
    assert doc.abstract == "A"  # a body-less document is still usable


def test_section_limits_truncate_with_a_warning(jats_xml, article_identifier) -> None:
    doc = parse_jats(jats_xml, article=article_identifier, limits=JatsLimits(max_sections=1))
    assert len(doc.sections) == 1
    assert any("truncated at 1 sections" in w for w in doc.warnings)


def test_nested_sections_do_not_duplicate_paragraph_text(article_identifier) -> None:
    # A parent <sec> must not absorb its subsection's paragraphs; each is its own
    # section, so pulling descendant <p> would report the child's text twice.
    xml = (
        "<article><body>"
        '<sec id="p1"><title>Parent</title><p>parent text</p>'
        '<sec id="c1"><title>Child</title><p>child text</p></sec>'
        "</sec></body></article>"
    )
    doc = parse_jats(xml, article=article_identifier)
    parent = doc.section(section_id="p1")
    child = doc.section(section_id="c1")
    assert parent.text == "parent text"
    assert child.text == "child text"


def test_abstract_only_fallback_document(article_identifier) -> None:
    record = ArticleRecord(
        identifiers=article_identifier,
        abstract="Only an abstract.",
        provider="europe_pmc",
        retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    doc = document_from_abstract(record)
    assert doc.source_format is SourceFormat.ABSTRACT
    assert doc.sections == [] and doc.tables == []
    assert doc.content_hash == content_hash("Only an abstract.")


def test_document_retrieved_at_must_be_timezone_aware(article_identifier) -> None:
    with pytest.raises(ValidationError):
        ArticleDocument(
            article=article_identifier,
            source_format=SourceFormat.ABSTRACT,
            content_hash="x",
            retrieved_at=datetime(2024, 1, 1),  # naive
        )
