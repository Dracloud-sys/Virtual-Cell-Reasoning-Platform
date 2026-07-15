"""Safe open-access document parsing (PR8c-1).

Turns an open-access JATS XML body (or, as a fallback, just an abstract) into a
typed :class:`ArticleDocument` that later extraction can anchor candidates to.

Safety posture — this parses untrusted third-party XML:

* **No entity expansion, no external references.** Entity declarations and external
  entity references are refused outright, so neither a billion-laughs bomb nor an
  external/network reference can be resolved.
* **Bounded.** The raw XML size and the number of sections/tables/rows/cells are all
  capped; exceeding a bound is a typed error or a recorded warning, never unbounded work.
* **Typed failure.** Malformed XML raises :class:`JatsParseError`. That is kept
  distinct from a well-formed document that simply has no body — the latter is a
  normal outcome with a warning.
* **No full text leaves the process.** The parsed body stays in the working
  :class:`ArticleDocument`; only :class:`DocumentMetadata` is put into a bundle.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from xml.etree import ElementTree  # noqa: S405 - entity constructs refused before parsing

from pydantic import BaseModel, Field, field_validator

from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    DocumentMetadata,
    SourceFormat,
)


class JatsParseError(ValueError):
    """Raised when XML is malformed, oversized, or uses forbidden entity constructs."""


class JatsLimits(BaseModel):
    """Explicit parsing bounds (a policy, not a biological constant)."""

    max_bytes: int = 8_000_000
    max_sections: int = 500
    max_tables: int = 100
    max_rows_per_table: int = 500
    max_cells_per_table: int = 5_000


class TableCell(BaseModel):
    row_index: int
    column_index: int
    text: str
    row_label: str | None = None
    column_label: str | None = None


class ArticleTable(BaseModel):
    table_id: str
    caption: str | None = None
    footnotes: list[str] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    cells: list[TableCell] = Field(default_factory=list)

    def cell(self, row_index: int, column_index: int) -> TableCell | None:
        for candidate in self.cells:
            if candidate.row_index == row_index and candidate.column_index == column_index:
                return candidate
        return None


class ArticleSection(BaseModel):
    section_id: str
    title: str | None = None
    text: str


class ArticleDocument(BaseModel):
    """A parsed document. Kept in-process: only :meth:`metadata` enters a bundle.

    Known limitations (deliberately not guessed at): table ``rowspan``/``colspan`` and
    composite/multi-row headers are not reconstructed, and a unit written only in a
    column header is **not** inherited by that column's cells.
    """

    article: ArticleIdentifier
    source_format: SourceFormat
    content_hash: str
    provider: str | None = None
    source_url: str | None = None
    retrieved_at: datetime
    license: str | None = None
    abstract: str | None = None
    sections: list[ArticleSection] = Field(default_factory=list)
    tables: list[ArticleTable] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("retrieved_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return v

    def section(self, *, title: str | None = None, section_id: str | None = None):
        for candidate in self.sections:
            if section_id is not None and candidate.section_id == section_id:
                return candidate
            if title is not None and candidate.title == title:
                return candidate
        return None

    def metadata(self) -> DocumentMetadata:
        return DocumentMetadata(
            article=self.article,
            source_format=self.source_format,
            content_hash=self.content_hash,
            provider=self.provider,
            source_url=self.source_url,
            retrieved_at=self.retrieved_at,
            license=self.license,
            section_count=len(self.sections),
            table_count=len(self.tables),
            warnings=list(self.warnings),
        )


def content_hash(text: str) -> str:
    """SHA-256 of the fetched source, so later runs can detect that it changed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- hardened parsing --------------------------------------------------------


# Any DTD/entity declaration is refused before parsing. This is what makes parsing
# safe: ElementTree never fetches external resources, so the remaining risks are
# internal entity expansion (billion laughs) and entity-smuggled content — both of
# which require a declaration. Numeric character references (&#177;) are unaffected,
# and an undeclared entity reference simply fails as malformed XML.
_FORBIDDEN_DECLARATION = re.compile(r"<!\s*(DOCTYPE|ENTITY)\b", re.IGNORECASE)


def _reject_entity_constructs(xml_text: str) -> None:
    if _FORBIDDEN_DECLARATION.search(xml_text):
        raise JatsParseError("XML DOCTYPE/ENTITY declarations are not allowed")


def _text(element) -> str:
    """All text under an element, preserving inline tags' content."""
    return " ".join("".join(element.itertext()).split())


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _find_all(root, name: str) -> list:
    return [e for e in root.iter() if _strip_ns(e.tag) == name]


def _child(element, name: str):
    for child in element:
        if _strip_ns(child.tag) == name:
            return child
    return None


def _parse_table(element, index: int, limits: JatsLimits, warnings: list[str]) -> ArticleTable:
    table_id = element.get("id") or f"table-{index + 1}"
    caption_el = _child(element, "caption")
    caption = _text(caption_el) if caption_el is not None else None
    footnotes = [_text(f) for f in _find_all(element, "table-wrap-foot")]

    headers: list[str] = []
    cells: list[TableCell] = []
    rows = [r for r in _find_all(element, "tr")]
    if len(rows) > limits.max_rows_per_table:
        warnings.append(f"table {table_id}: truncated to {limits.max_rows_per_table} rows")
        rows = rows[: limits.max_rows_per_table]

    body_row = 0
    for row in rows:
        entries = [c for c in row if _strip_ns(c.tag) in ("th", "td")]
        is_header = all(_strip_ns(c.tag) == "th" for c in entries) and entries
        if is_header and not headers:
            headers = [_text(c) for c in entries]
            continue
        row_label = _text(entries[0]) if entries else None
        for column_index, entry in enumerate(entries):
            if len(cells) >= limits.max_cells_per_table:
                warnings.append(
                    f"table {table_id}: truncated at {limits.max_cells_per_table} cells"
                )
                break
            cells.append(
                TableCell(
                    row_index=body_row,
                    column_index=column_index,
                    text=_text(entry),
                    row_label=row_label,
                    column_label=headers[column_index] if column_index < len(headers) else None,
                )
            )
        body_row += 1
    return ArticleTable(
        table_id=table_id, caption=caption, footnotes=footnotes, headers=headers, cells=cells
    )


def parse_jats(
    xml_text: str,
    *,
    article: ArticleIdentifier,
    provider: str | None = None,
    source_url: str | None = None,
    retrieved_at: datetime | None = None,
    limits: JatsLimits | None = None,
) -> ArticleDocument:
    """Parse open-access JATS XML into an :class:`ArticleDocument`.

    Raises :class:`JatsParseError` for malformed/oversized/entity-bearing XML. A
    well-formed document with no ``<body>`` is *not* an error — it yields an empty
    section list plus a warning.
    """
    limits = limits or JatsLimits()
    if len(xml_text.encode("utf-8")) > limits.max_bytes:
        raise JatsParseError(f"XML exceeds the {limits.max_bytes}-byte limit")
    _reject_entity_constructs(xml_text)

    try:
        root = ElementTree.fromstring(xml_text)  # noqa: S314 - entities refused above
    except ElementTree.ParseError as exc:
        raise JatsParseError(f"malformed JATS XML: {exc}") from exc

    warnings: list[str] = []

    abstract_el = next(iter(_find_all(root, "abstract")), None)
    abstract = _text(abstract_el) if abstract_el is not None else None

    license_el = next(iter(_find_all(root, "license")), None)
    license_text = None
    if license_el is not None:
        license_text = license_el.get("{http://www.w3.org/1999/xlink}href") or (
            _text(license_el) or None
        )

    body = next(iter(_find_all(root, "body")), None)
    sections: list[ArticleSection] = []
    if body is None:
        warnings.append("document has no <body>; only abstract-level text is available")
    else:
        for index, sec in enumerate(_find_all(body, "sec")):
            if len(sections) >= limits.max_sections:
                warnings.append(f"truncated at {limits.max_sections} sections")
                break
            title_el = _child(sec, "title")
            # Only this section's own paragraphs: a nested <sec> is emitted as its own
            # section, so pulling descendant <p> here would duplicate its text.
            paragraphs = [_text(p) for p in sec if _strip_ns(p.tag) == "p"]
            sections.append(
                ArticleSection(
                    section_id=sec.get("id") or f"sec-{index + 1}",
                    title=_text(title_el) if title_el is not None else None,
                    text=" ".join(t for t in paragraphs if t),
                )
            )

    tables: list[ArticleTable] = []
    for index, wrap in enumerate(_find_all(root, "table-wrap")):
        if len(tables) >= limits.max_tables:
            warnings.append(f"truncated at {limits.max_tables} tables")
            break
        tables.append(_parse_table(wrap, index, limits, warnings))

    return ArticleDocument(
        article=article,
        source_format=SourceFormat.JATS_XML,
        content_hash=content_hash(xml_text),
        provider=provider,
        source_url=source_url,
        retrieved_at=retrieved_at or datetime.now(UTC),
        license=license_text,
        abstract=abstract,
        sections=sections,
        tables=tables,
        warnings=warnings,
    )


def document_from_abstract(record: ArticleRecord) -> ArticleDocument:
    """Abstract-only fallback for an article with no open-access full text."""
    abstract = record.abstract or ""
    return ArticleDocument(
        article=record.identifiers,
        source_format=SourceFormat.ABSTRACT,
        content_hash=content_hash(abstract),
        provider=record.provider,
        source_url=record.source_url,
        retrieved_at=record.retrieved_at or datetime.now(UTC),
        abstract=record.abstract,
        warnings=[] if record.abstract else ["article has no abstract text"],
    )
