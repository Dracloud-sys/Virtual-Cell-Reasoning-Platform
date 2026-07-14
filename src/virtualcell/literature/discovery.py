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
    RelevanceComponent,
    RelevanceResult,
    normalize_title,
)
from virtualcell.literature.providers.base import LiteratureProvider

# Filters whose complete absence from a hit is worth flagging for review.
_CRITICAL = ("species", "cell_types", "genes")


class BuiltQuery(BaseModel):
    """A provider query string plus the expansions actually applied (audit trail)."""

    query_string: str
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


def build_europe_pmc_query(query: LiteratureQuery) -> BuiltQuery:
    """Build a deterministic Europe PMC query from a :class:`LiteratureQuery`.

    Only the caller-provided synonyms are used (joined with OR) — the builder never
    invents species/cell-type synonyms — and every expansion applied is recorded.
    """
    parts: list[str] = [f'("{_sanitize(query.query_text)}")']
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
    return BuiltQuery(query_string=" AND ".join(parts), expansions=expansions)


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


def _merge(primary: ArticleRecord, other: ArticleRecord) -> ArticleRecord:
    """Fill gaps in ``primary`` from ``other`` without overwriting present fields."""
    update: dict = {}
    ident = primary.identifiers.model_copy()
    for attr in ("doi", "pmid", "pmcid", "provider_id"):
        if getattr(ident, attr) is None and getattr(other.identifiers, attr) is not None:
            setattr(ident, attr, getattr(other.identifiers, attr))
    update["identifiers"] = ident
    for attr in ("title", "abstract", "journal", "publication_year", "publication_status"):
        if getattr(primary, attr) in (None, "") and getattr(other, attr) not in (None, ""):
            update[attr] = getattr(other, attr)
    if not primary.authors and other.authors:
        update["authors"] = other.authors
    # Retraction / availability are OR-merged: a positive signal from either wins.
    update["is_retracted"] = primary.is_retracted or other.is_retracted
    update["has_full_text"] = primary.has_full_text or other.has_full_text
    update["has_supplementary"] = primary.has_supplementary or other.has_supplementary
    update["is_open_access"] = primary.is_open_access or other.is_open_access
    return primary.model_copy(update=update)


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
            result[found] = _merge(result[found], article)

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
