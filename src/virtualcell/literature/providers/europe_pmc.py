"""Europe PMC connector (bounded, injectable, offline-testable).

Europe PMC exposes an official public REST API over PubMed-class metadata with
open-access full-text XML. This connector uses only that API — no scraping, no
paywall circumvention. All networking goes through an injected
:class:`~virtualcell.literature.providers.base.HttpTransport`, so tests use a fake
transport and never hit the network.

Verified endpoints (see the API docs / a live `resultType=core` response):

* search: ``GET /europepmc/webservices/rest/search`` with ``query``, ``format=json``,
  ``resultType=core``, ``pageSize`` and cursor pagination via ``cursorMark`` /
  ``nextCursorMark`` (start at ``*``); response carries ``hitCount`` and
  ``resultList.result[]`` with ``id``, ``source``, ``pmid``, ``pmcid``, ``doi``,
  ``title``, ``abstractText``, ``authorString``, ``pubYear``, ``pubTypeList``,
  ``publicationStatus``, ``isOpenAccess`` (Y/N), ``inPMC``/``inEPMC`` (Y/N),
  ``hasSuppl`` (Y/N), ``commentCorrectionList``.
* open full text: ``GET /europepmc/webservices/rest/{source}/{pmcid}/fullTextXML``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep
from urllib.parse import quote

from pydantic import ValidationError

from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    LiteratureQuery,
    LiteratureSearchResult,
    ProviderProvenance,
    PublicationNotice,
    PublicationNoticeKind,
)
from virtualcell.literature.discovery import build_europe_pmc_query
from virtualcell.literature.providers.base import (
    HttpResponse,
    HttpTransport,
    ProviderError,
    UrllibTransport,
)

_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_PAGE_SIZE_CAP = 100
# Transient statuses worth a bounded retry (rate limit + server errors). Other 4xx
# are client errors and are not retried.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class EuropePmcProvider:
    """Bounded Europe PMC provider. Network is injected; tests pass a fake transport."""

    name = "europe_pmc"

    def __init__(
        self,
        transport: HttpTransport | None = None,
        *,
        max_pages: int = 5,
        retries: int = 2,
        timeout: float = 10.0,
        backoff: float = 0.0,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if min(max_pages, retries, timeout, backoff) < 0:
            raise ValueError("max_pages, retries, timeout and backoff must be non-negative")
        self.transport = transport or UrllibTransport()
        self.max_pages = max_pages
        self.retries = retries
        self.timeout = timeout
        self.backoff = backoff
        self.sleeper = sleeper

    # -- networking ---------------------------------------------------------

    def _fetch(self, url: str, *, ok_statuses: frozenset[int] = frozenset()) -> HttpResponse:
        """Fetch with bounded retry on transport errors and transient statuses.

        A non-retryable HTTP error raises ``ProviderError``; statuses in
        ``ok_statuses`` (e.g. 404 for missing full text) are returned to the caller.
        """
        last: ProviderError | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.transport.get(url, timeout=self.timeout)
            except ProviderError as exc:
                last = exc
            else:
                if response.ok or response.status_code in ok_statuses:
                    return response
                if response.status_code not in _RETRYABLE_STATUS:
                    raise ProviderError(f"europe_pmc returned HTTP {response.status_code}")
                last = ProviderError(f"europe_pmc returned HTTP {response.status_code}")
            if attempt < self.retries:
                self.sleeper(self.backoff * (attempt + 1))
        raise last or ProviderError("europe_pmc request failed")

    @staticmethod
    def _parse(text: str) -> dict:
        try:
            data = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ProviderError(f"europe_pmc returned malformed JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("europe_pmc response was not a JSON object")
        return data

    # -- search -------------------------------------------------------------

    def search(self, query: LiteratureQuery) -> LiteratureSearchResult:
        built = build_europe_pmc_query(query)
        try:
            return self._search(query, built.query_string)
        except ProviderError as exc:
            # Attach provider/query context so callers stay provider-agnostic.
            if exc.query_sent is None:
                exc.query_sent = built.query_string
            if exc.provider is None:
                exc.provider = self.name
            raise

    def _search(self, query: LiteratureQuery, query_string: str) -> LiteratureSearchResult:
        retrieved_at = datetime.now(UTC)
        page_size = min(query.max_results, _PAGE_SIZE_CAP)
        articles: list[ArticleRecord] = []
        warnings: list[str] = []
        hit_count: int | None = None
        cursor = "*"
        pages = 0

        while len(articles) < query.max_results and pages < self.max_pages:
            url = (
                f"{_BASE}/search?query={quote(query_string)}"
                f"&format=json&resultType=core&pageSize={page_size}&cursorMark={quote(cursor)}"
            )
            data = self._parse(self._fetch(url).text)
            hit_count = data.get("hitCount", hit_count)
            results = data.get("resultList", {}).get("result", []) or []
            for raw in results:
                try:
                    articles.append(_to_record(raw, retrieved_at))
                except (ValidationError, ValueError, KeyError, TypeError) as exc:
                    # A single malformed row is skipped with a warning, not fatal.
                    warnings.append(f"skipped malformed record: {exc}")
                if len(articles) >= query.max_results:
                    break
            pages += 1
            next_cursor = data.get("nextCursorMark")
            if not results or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        provenance = ProviderProvenance(
            provider=self.name,
            query_sent=query_string,
            query_mode=query.query_mode.value,
            retrieved_at=retrieved_at,
            hit_count=hit_count,
            page_size=page_size,
            pages_fetched=pages,
        )
        return LiteratureSearchResult(
            provenance=provenance, articles=articles[: query.max_results], warnings=warnings
        )

    def fetch_record(self, identifier: ArticleIdentifier) -> ArticleRecord:
        """Fetch a single record by identifier via a targeted search."""
        if identifier.pmcid:
            term = f"PMCID:{identifier.pmcid}"
        elif identifier.pmid:
            term = f"EXT_ID:{identifier.pmid} AND SRC:MED"
        elif identifier.doi:
            term = f'DOI:"{identifier.doi}"'
        else:
            raise ProviderError("fetch_record requires a pmcid, pmid, or doi")
        url = f"{_BASE}/search?query={quote(term)}&format=json&resultType=core&pageSize=1"
        data = self._parse(self._fetch(url).text)
        results = data.get("resultList", {}).get("result", []) or []
        if not results:
            raise ProviderError(f"no record found for {identifier!r}")
        return _to_record(results[0], datetime.now(UTC))

    def fetch_open_full_text(self, identifier: ArticleIdentifier) -> str | None:
        """Return open-access full-text XML, or ``None`` if not openly available."""
        if not identifier.pmcid:
            return None
        url = f"{_BASE}/PMC/{quote(identifier.pmcid)}/fullTextXML"
        response = self._fetch(url, ok_statuses=frozenset({404}))
        if response.status_code == 404:
            return None
        return response.text


# --- response mapping (metadata only — never a biological claim) -------------


def _yn(value: object) -> bool:
    return value == "Y"


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _authors(raw: dict) -> list[str]:
    author_list = raw.get("authorList", {}).get("author", []) or []
    names = [a.get("fullName") for a in author_list if a.get("fullName")]
    if names:
        return names
    author_string = raw.get("authorString")
    if author_string:
        return [a.strip().rstrip(".") for a in author_string.split(",") if a.strip()]
    return []


def _publication_types(raw: dict) -> list[str]:
    return [t for t in (raw.get("pubTypeList", {}).get("pubType", []) or []) if t]


# Order matters: check the more specific "expression of concern" before "concern".
_NOTICE_KINDS = (
    ("retract", PublicationNoticeKind.RETRACTION),
    ("erratum", PublicationNoticeKind.ERRATUM),
    ("expression of concern", PublicationNoticeKind.EXPRESSION_OF_CONCERN),
    ("concern", PublicationNoticeKind.EXPRESSION_OF_CONCERN),
    ("correct", PublicationNoticeKind.CORRECTION),
)


def _notices(raw: dict) -> list[PublicationNotice]:
    notices: list[PublicationNotice] = []
    comments = raw.get("commentCorrectionList", {}).get("commentCorrection", []) or []
    for comment in comments:
        text = (comment.get("type") or "").lower()
        for needle, kind in _NOTICE_KINDS:
            if needle in text:
                reference = comment.get("id") or comment.get("reference")
                notices.append(PublicationNotice(kind=kind, reference=reference))
                break
    return notices


def _is_retracted(raw: dict, notices: list[PublicationNotice]) -> bool:
    # A retraction notice, pub-type, or status — but NOT a correction/erratum/EoC.
    if any(n.kind is PublicationNoticeKind.RETRACTION for n in notices):
        return True
    if any("retract" in t.lower() for t in _publication_types(raw)):
        return True
    return "retract" in (raw.get("publicationStatus") or "").lower()


def _journal(raw: dict) -> str | None:
    info = raw.get("journalInfo", {}).get("journal", {})
    return info.get("title") or raw.get("journalTitle")


def _source_url(raw: dict) -> str | None:
    pmcid, pmid = raw.get("pmcid"), raw.get("pmid")
    if pmcid:
        return f"https://europepmc.org/article/PMC/{pmcid}"
    if pmid:
        return f"https://europepmc.org/article/MED/{pmid}"
    return None


def _to_record(raw: dict, retrieved_at: datetime) -> ArticleRecord:
    notices = _notices(raw)
    return ArticleRecord(
        identifiers=ArticleIdentifier(
            doi=raw.get("doi"),
            pmid=raw.get("pmid"),
            pmcid=raw.get("pmcid"),
            provider_id=raw.get("id"),
        ),
        title=raw.get("title"),
        abstract=raw.get("abstractText"),
        authors=_authors(raw),
        journal=_journal(raw),
        publication_year=_int(raw.get("pubYear")),
        publication_types=_publication_types(raw),
        publication_status=raw.get("publicationStatus"),
        is_open_access=_yn(raw.get("isOpenAccess")),
        has_full_text=_yn(raw.get("inPMC")) or _yn(raw.get("inEPMC")),
        has_supplementary=_yn(raw.get("hasSuppl")),
        is_retracted=_is_retracted(raw, notices),
        notices=notices,
        provider="europe_pmc",
        source_url=_source_url(raw),
        retrieved_at=retrieved_at,
    )
