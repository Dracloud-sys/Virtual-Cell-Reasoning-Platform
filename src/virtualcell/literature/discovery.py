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


def _identity_keys(article: ArticleRecord) -> list[tuple[str, str]]:
    """Identity keys in priority order: PMCID, PMID, normalized DOI, then title."""
    keys: list[tuple[str, str]] = []
    ident = article.identifiers
    if ident.pmcid:
        keys.append(("pmcid", ident.pmcid))
    if ident.pmid:
        keys.append(("pmid", ident.pmid))
    if ident.normalized_doi:
        keys.append(("doi", ident.normalized_doi))
    title = normalize_title(article.title)
    if title:
        keys.append(("title", title))
    return keys


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


def deduplicate_articles(articles: list[ArticleRecord]) -> list[ArticleRecord]:
    """Merge records that refer to the same paper (PMCID > PMID > DOI > title).

    Title matching is a last-resort fallback and can over-merge two distinct papers
    that share a normalized title — real duplicates almost always share a stronger
    id, so this is an accepted, documented limitation of the fallback.
    """
    result: list[ArticleRecord] = []
    index: dict[tuple[str, str], int] = {}
    for article in articles:
        found: int | None = None
        for key in _identity_keys(article):
            if key in index:
                found = index[key]
                break
        if found is None:
            result.append(article)
            found = len(result) - 1
        else:
            result[found] = _merge(result[found], article)
        for key in _identity_keys(result[found]):
            index.setdefault(key, found)
    return result


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
        (score_relevance(a, query) for a in deduped),
        key=lambda r: r.total_score,
        reverse=True,
    )
    return LiteratureEvidenceBundle(
        query=query,
        provider_provenance=result.provenance,
        articles=deduped,
        relevance=relevance,
    )
