"""Deterministic query building, deduplication, and transparent relevance scoring.

None of this uses an LLM: the same :class:`LiteratureQuery` always produces the
same provider query, the same dedup result, and the same relevance breakdown.
Relevance here is *search* relevance only — it is never reused as evidence strength
or claim confidence.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from virtualcell.literature.contracts import (
    ArticleRecord,
    DiscoveryRunStatus,
    LiteratureEvidenceBundle,
    LiteratureQuery,
    QueryMode,
    RelevanceComponent,
    RelevanceResult,
    normalize_title,
)
from virtualcell.literature.providers.base import LiteratureProvider

# Filters whose complete absence from a hit is worth flagging for review.
_CRITICAL = ("species", "cell_types", "genes")


# A conservative, deterministic English function-word/query-frame list. It contains no
# biology: gene symbols, markers and numbers are never dropped.
_STOPWORDS = frozenset(
    """
    a an the and or of in on at for with to from by is are was were be been being
    do does did can could would should will what which who how why when where that
    this these those it its as into about find finds paper papers study studies
    show shows please we i us using use related regarding any all
    """.split()  # noqa: SIM905 - a readable word list, not a literal to hand-maintain
)


class BuiltQuery(BaseModel):
    """A provider query string plus the mode, tokens and expansions applied (audit trail)."""

    query_string: str
    query_mode: QueryMode
    tokens_kept: list[str] = Field(default_factory=list)
    tokens_dropped: list[str] = Field(default_factory=list)
    expansions: dict[str, list[str]] = Field(default_factory=dict)


def _sanitize(term: str) -> str:
    """Drop quote/backslash so a term can be safely phrase-quoted (no query injection)."""
    return re.sub(r'["\\]', " ", term).strip()


def _or_group(terms: list[str]) -> tuple[str, list[str]] | None:
    quoted = [f'"{s}"' for t in terms if (s := _sanitize(t))]
    used = [t for t in terms if _sanitize(t)]
    if not quoted:
        return None
    return "(" + " OR ".join(quoted) + ")", used


class QueryBuildError(ValueError):
    """Raised when a query_text has no searchable tokens left after normalization."""


def _split_tokens(text: str) -> list[str]:
    """Normalize punctuation and split into alphanumeric tokens.

    Separators (``/``, ``-``, commas, …) split, so ``TERT/CDK4-mediated`` yields
    ``TERT``, ``CDK4``, ``mediated`` and ``SA-beta-gal`` yields its parts — each is a
    real index term. Digits are preserved (``p16``, ``p21`` survive intact).
    """
    return [t for t in re.split(r"[^A-Za-z0-9]+", text) if len(t) >= 2]


def _terms_clause(query: LiteratureQuery) -> tuple[str, list[str], list[str]]:
    """TERMS mode: AND the meaningful tokens, dropping deterministic stopwords."""
    tokens = _split_tokens(query.query_text)
    kept = [t for t in tokens if t.lower() not in _STOPWORDS]
    dropped = [t for t in tokens if t.lower() in _STOPWORDS]
    if not kept:
        raise QueryBuildError(
            "query_text has no searchable tokens after stopword removal "
            f"(dropped: {dropped}); use query_mode='phrase' or a more specific query"
        )
    return "(" + " AND ".join(f'"{t}"' for t in kept) + ")", kept, dropped


def build_europe_pmc_query(query: LiteratureQuery) -> BuiltQuery:
    """Build a deterministic Europe PMC query from a :class:`LiteratureQuery`.

    ``query_text`` becomes a clause per :class:`QueryMode`: ``terms`` normalizes
    punctuation, drops a fixed English stopword list and ANDs what remains (so a prose
    question does not turn every function word into a filter); ``phrase`` keeps the
    exact phrase. Only caller-provided synonyms are OR-joined (no invented synonyms),
    and the mode, kept/dropped tokens and expansions are all recorded.
    """
    if query.query_mode == QueryMode.PHRASE:
        clause, kept, dropped = f'("{_sanitize(query.query_text)}")', [], []
    else:
        clause, kept, dropped = _terms_clause(query)
    parts: list[str] = [clause]
    expansions: dict[str, list[str]] = {}
    for field, terms in (
        ("species", query.species),
        ("cell_types", query.cell_types),
        ("genes", query.genes),
        ("phenotypes", query.phenotypes),
        ("assays", query.assays),
    ):
        group = _or_group(terms)
        if group is not None:
            clause, used = group
            parts.append(clause)
            expansions[field] = used
    if query.year_from is not None or query.year_to is not None:
        lo = query.year_from if query.year_from is not None else 1500
        hi = query.year_to if query.year_to is not None else 3000
        parts.append(f"PUB_YEAR:[{lo} TO {hi}]")
    if query.open_access_only:
        parts.append("OPEN_ACCESS:Y")
    return BuiltQuery(
        query_string=" AND ".join(parts),
        query_mode=query.query_mode,
        tokens_kept=kept,
        tokens_dropped=dropped,
        expansions=expansions,
    )


# --- deduplication -----------------------------------------------------------


def _strong_keys(article: ArticleRecord) -> list[tuple[str, str]]:
    """Strong identity keys (PMCID, PMID, normalized DOI). ``provider_id`` is
    deliberately excluded — it is provider-scoped, not a cross-provider identity."""
    keys: list[tuple[str, str]] = []
    ident = article.identifiers
    if ident.pmcid:
        keys.append(("pmcid", ident.pmcid))
    if ident.pmid:
        keys.append(("pmid", ident.pmid))
    if ident.normalized_doi:
        keys.append(("doi", ident.normalized_doi))
    return keys


def _strong_conflict(a: ArticleRecord, b: ArticleRecord) -> list[str]:
    """Reasons two records have *conflicting* strong ids (same field, different value)."""
    reasons: list[str] = []
    ai, bi = a.identifiers, b.identifiers
    if ai.pmid and bi.pmid and ai.pmid != bi.pmid:
        reasons.append(f"pmid {ai.pmid} != {bi.pmid}")
    if ai.pmcid and bi.pmcid and ai.pmcid != bi.pmcid:
        reasons.append(f"pmcid {ai.pmcid} != {bi.pmcid}")
    if ai.normalized_doi and bi.normalized_doi and ai.normalized_doi != bi.normalized_doi:
        reasons.append(f"doi {ai.normalized_doi} != {bi.normalized_doi}")
    return reasons


def _union(first: list, second: list) -> list:
    """Order-preserving union (first wins ordering; duplicates dropped)."""
    merged = list(first)
    for item in second:
        if item not in merged:
            merged.append(item)
    return merged


def _merge(primary: ArticleRecord, other: ArticleRecord) -> tuple[ArticleRecord, list[str]]:
    """Merge ``other`` into ``primary``, returning the record and any conflict notes.

    Gaps are filled but present values are never overwritten; **list metadata is
    unioned** (a correction notice found only on the second record must survive), and
    a disagreement between two present scalars is reported rather than hidden.
    """
    warnings: list[str] = []
    update: dict = {}

    ident = primary.identifiers.model_copy()
    for attr in ("doi", "pmid", "pmcid", "provider_id"):
        if getattr(ident, attr) is None and getattr(other.identifiers, attr) is not None:
            setattr(ident, attr, getattr(other.identifiers, attr))
    update["identifiers"] = ident

    for attr in ("title", "abstract", "journal", "publication_year", "publication_status"):
        mine, theirs = getattr(primary, attr), getattr(other, attr)
        if mine in (None, "") and theirs not in (None, ""):
            update[attr] = theirs
        elif mine not in (None, "") and theirs not in (None, "") and mine != theirs:
            warnings.append(f"conflicting {attr} while merging duplicates; kept {mine!r}")

    if not primary.authors and other.authors:
        update["authors"] = other.authors
    # List metadata is unioned so a signal present on only one record is not lost.
    update["publication_types"] = _union(primary.publication_types, other.publication_types)
    update["notices"] = _union(primary.notices, other.notices)
    # Retraction / availability are OR-merged: a positive signal from either wins.
    update["is_retracted"] = primary.is_retracted or other.is_retracted
    update["has_full_text"] = primary.has_full_text or other.has_full_text
    update["has_supplementary"] = primary.has_supplementary or other.has_supplementary
    update["is_open_access"] = primary.is_open_access or other.is_open_access
    return primary.model_copy(update=update), warnings


class DedupResult(BaseModel):
    """Deduplicated articles plus any identity conflicts surfaced during merging."""

    articles: list[ArticleRecord] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


def deduplicate_articles(articles: list[ArticleRecord]) -> DedupResult:
    """Merge records that refer to the same paper.

    A **strong** identifier match (PMCID / PMID / normalized DOI) merges records.
    The **title** fallback merges only when it does *not* contradict a strong id —
    two papers with the same title but different PMIDs/DOIs stay separate (the
    original bug silently dropped one). Merging fills gaps without overwriting a
    present identifier; where two merged records disagree on a strong id (e.g. same
    DOI, different PMID) the conflict is reported rather than hidden.
    """
    result: list[ArticleRecord] = []
    strong_index: dict[tuple[str, str], int] = {}
    title_index: dict[str, int] = {}
    conflicts: list[str] = []

    for article in articles:
        found: int | None = None
        for key in _strong_keys(article):
            if key in strong_index:
                found = strong_index[key]
                break
        if found is None:
            title = normalize_title(article.title)
            if title and title in title_index:
                candidate = title_index[title]
                if not _strong_conflict(result[candidate], article):
                    found = candidate

        if found is None:
            result.append(article)
            found = len(result) - 1
        else:
            for reason in _strong_conflict(result[found], article):
                conflicts.append(f"merged records with conflicting identifiers: {reason}")
            result[found], merge_warnings = _merge(result[found], article)
            conflicts.extend(merge_warnings)

        for key in _strong_keys(result[found]):
            strong_index.setdefault(key, found)
        title = normalize_title(result[found].title)
        if title:
            title_index.setdefault(title, found)
    return DedupResult(articles=result, conflicts=conflicts)


# --- relevance (search relevance only) --------------------------------------


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2]


def score_relevance(article: ArticleRecord, query: LiteratureQuery) -> RelevanceResult:
    """A transparent, additive relevance score with a per-component breakdown.

    NOTE: this measures how well an article matches the *search*, not how strong or
    trustworthy its science is. It must not be reused as evidence strength.
    """
    haystack = " ".join(filter(None, [article.title, article.abstract])).lower()
    title = (article.title or "").lower()
    components: list[RelevanceComponent] = []
    matched_all: list[str] = []
    group_matched: dict[str, list[str]] = {}

    def add_group(name: str, terms: list[str], weight: float) -> None:
        if not terms:
            return
        matched = [t for t in terms if t.lower() in haystack]
        group_matched[name] = matched
        matched_all.extend(matched)
        components.append(
            RelevanceComponent(
                name=name,
                matched=matched,
                weight=weight,
                score=round(weight * len(matched) / len(terms), 3),
            )
        )

    q_tokens = _tokens(query.query_text)
    if q_tokens:
        q_matched = [t for t in q_tokens if t in haystack]
        matched_all.extend(q_matched)
        components.append(
            RelevanceComponent(
                name="query_terms",
                matched=q_matched,
                weight=2.0,
                score=round(2.0 * len(q_matched) / len(q_tokens), 3),
            )
        )
        title_matched = [t for t in q_tokens if t in title]
        components.append(
            RelevanceComponent(
                name="title_match",
                matched=title_matched,
                weight=1.0,
                score=round(len(title_matched) / len(q_tokens), 3),
            )
        )

    add_group("species", query.species, 2.0)
    add_group("cell_types", query.cell_types, 1.5)
    add_group("genes", query.genes, 2.0)
    add_group("phenotypes", query.phenotypes, 1.0)
    add_group("assays", query.assays, 1.0)

    availability = (0.5 if article.has_full_text else 0.0) + (
        0.25 if article.has_supplementary else 0.0
    )
    components.append(
        RelevanceComponent(name="availability", matched=[], weight=0.75, score=availability)
    )

    missing = [name for name in _CRITICAL if getattr(query, name) and not group_matched.get(name)]
    return RelevanceResult(
        article=article.identifiers,
        total_score=round(sum(c.score for c in components), 3),
        matched_terms=sorted(set(matched_all)),
        missing_critical_filters=missing,
        breakdown=components,
    )


def discover(query: LiteratureQuery, provider: LiteratureProvider) -> LiteratureEvidenceBundle:
    """Run one discovery pass: search -> dedup -> relevance-ranked bundle.

    The bundle carries article *metadata* and relevance only; extraction,
    verification and canonical conversion are later slices. Nothing here produces a
    biological claim or writes to the KnowledgeStore.
    """
    result = provider.search(query)
    deduped = deduplicate_articles(result.articles)
    relevance = sorted(
        (score_relevance(a, query) for a in deduped.articles),
        key=lambda r: r.total_score,
        reverse=True,
    )
    status = DiscoveryRunStatus.SUCCESS if deduped.articles else DiscoveryRunStatus.ZERO_RESULTS
    return LiteratureEvidenceBundle(
        query=query,
        provider_provenance=result.provenance,
        run_status=status,
        articles=deduped.articles,
        relevance=relevance,
        warnings=[*result.warnings, *deduped.conflicts],
    )
