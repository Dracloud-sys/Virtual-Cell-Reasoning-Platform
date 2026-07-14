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
from datetime import UTC, datetime
from urllib.parse import quote

from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    LiteratureQuery,
    LiteratureSearchResult,
    ProviderProvenance,
)
from virtualcell.literature.discovery import build_europe_pmc_query
from virtualcell.literature.providers.base import (
    HttpTransport,
    ProviderError,
    UrllibTransport,
)

_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_PAGE_SIZE_CAP = 100


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
    ) -> None:
        self.transport = transport or UrllibTransport()
        self.max_pages = max_pages
        self.retries = retries
        self.timeout = timeout

    # -- networking ---------------------------------------------------------

    def _get_with_retry(self, url: str):
        last: ProviderError | None = None
        for _ in range(self.retries + 1):
            try:
                return self.transport.get(url, timeout=self.timeout)
            except ProviderError as exc:  # transport failure; bounded retry
                last = exc
        assert last is not None
        raise last

    # -- search -------------------------------------------------------------

    def search(self, query: LiteratureQuery) -> LiteratureSearchResult:
        built = build_europe_pmc_query(query)
        retrieved_at = datetime.now(UTC)
        page_size = min(query.max_results, _PAGE_SIZE_CAP)
        articles: list[ArticleRecord] = []
        hit_count: int | None = None
        cursor = "*"
        pages = 0

        while len(articles) < query.max_results and pages < self.max_pages:
            url = (
                f"{_BASE}/search?query={quote(built.query_string)}"
                f"&format=json&resultType=core&pageSize={page_size}&cursorMark={quote(cursor)}"
            )
            response = self._get_with_retry(url)
            if not response.ok:
                # A non-2xx status is a provider failure, never a silent empty result.
                raise ProviderError(f"europe_pmc search returned HTTP {response.status_code}")
            data = json.loads(response.text)
            hit_count = data.get("hitCount", hit_count)
            results = data.get("resultList", {}).get("result", []) or []
            for raw in results:
                articles.append(_to_record(raw, retrieved_at))
                if len(articles) >= query.max_results:
                    break
            pages += 1
            next_cursor = data.get("nextCursorMark")
            if not results or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        provenance = ProviderProvenance(
            provider=self.name,
            query_sent=built.query_string,
            retrieved_at=retrieved_at,
            hit_count=hit_count,
            page_size=page_size,
            pages_fetched=pages,
        )
        return LiteratureSearchResult(provenance=provenance, articles=articles[: query.max_results])

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
        response = self._get_with_retry(url)
        if not response.ok:
            raise ProviderError(f"europe_pmc fetch_record returned HTTP {response.status_code}")
        results = json.loads(response.text).get("resultList", {}).get("result", []) or []
        if not results:
            raise ProviderError(f"no record found for {identifier!r}")
        return _to_record(results[0], datetime.now(UTC))

    def fetch_open_full_text(self, identifier: ArticleIdentifier) -> str | None:
        """Return open-access full-text XML, or ``None`` if not openly available."""
        if not identifier.pmcid:
            return None
        url = f"{_BASE}/PMC/{quote(identifier.pmcid)}/fullTextXML"
        response = self._get_with_retry(url)
        if response.status_code == 404:
            return None
        if not response.ok:
            raise ProviderError(f"europe_pmc full text returned HTTP {response.status_code}")
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


def _is_retracted(raw: dict) -> bool:
    types = {t.lower() for t in _publication_types(raw)}
    if any("retract" in t for t in types):
        return True
    status = (raw.get("publicationStatus") or "").lower()
    if "retract" in status:
        return True
    comments = raw.get("commentCorrectionList", {}).get("commentCorrection", []) or []
    return any("retract" in (c.get("type") or "").lower() for c in comments)


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
        is_retracted=_is_retracted(raw),
        provider="europe_pmc",
        source_url=_source_url(raw),
        retrieved_at=retrieved_at,
    )
