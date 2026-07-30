"""Resolve literature markers onto curated ontology nodes (PR9-c).

PR8e ingests literature evidence under a ``lit:`` namespace, deliberately kept apart from
curated truth. This module adds a *conservative* bridge so discovered evidence becomes
reachable from the known ontology without being merged into it or upgraded past a
hypothesis: a ``lit:marker`` node is linked to the curated entity that carries the same
name/symbol/alias, by a **weak, reviewable** ``ASSOCIATED_WITH`` edge.

Discipline (mirrors ingestion): only an **exact normalized** name/symbol/alias match
resolves — no fuzzy matching, no synonyms — and an ambiguous match (several curated
candidates) is left unresolved rather than guessed. The two nodes stay separate (a link is
added, never a merge), the edge is tagged ``review_status = "pending_review"`` with
provenance, and resolution is deterministic and idempotent.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from virtualcell.knowledge.schema import BioEntity, Interaction, RelationType
from virtualcell.knowledge.store import KnowledgeStore

# The one (weak, symmetric) relation resolution is allowed to assert.
RESOLUTION_RELATION = RelationType.ASSOCIATED_WITH
REVIEW_STATUS = "pending_review"
RESOLUTION_CONFIDENCE = 0.3
_LIT_PREFIX = "lit:"


class ResolutionReport(BaseModel):
    """A deterministic summary of marker resolution (for reporting/tests)."""

    resolved: list[tuple[str, str]] = Field(default_factory=list)  # (lit_marker_id, curated_id)
    unresolved: list[str] = Field(default_factory=list)  # no curated match
    ambiguous: list[str] = Field(default_factory=list)  # several curated matches
    edges_added: int = 0


def _normalize(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _curated_matches(store: KnowledgeStore, marker: BioEntity) -> list[BioEntity]:
    """Curated (non-``lit:``) entities whose name/symbol/alias exactly matches the marker."""
    key = _normalize(marker.name)
    if not key:
        return []
    found: dict[str, BioEntity] = {}
    for candidate in store.search(marker.name, k=25):
        if candidate.id.startswith(_LIT_PREFIX):
            continue
        names = [candidate.name, *candidate.aliases, getattr(candidate, "symbol", None)]
        if any(_normalize(name) == key for name in names if name):
            found[candidate.id] = candidate
    return list(found.values())


def resolve_literature_markers(store: KnowledgeStore, marker_ids: list[str]) -> ResolutionReport:
    """Link each given ``lit:marker`` to its curated ontology node, weakly and reviewably.

    Deterministic and idempotent: an exact single match is linked (the edge added only if
    absent), no match is left unresolved, and several matches are recorded as ambiguous and
    skipped — never guessed.
    """
    report = ResolutionReport()
    for marker_id in marker_ids:
        marker = store.get(marker_id)
        if marker is None:  # pragma: no cover - caller passes ingested ids
            continue
        matches = _curated_matches(store, marker)
        if not matches:
            report.unresolved.append(marker_id)
            continue
        if len(matches) > 1:
            report.ambiguous.append(marker_id)
            continue
        curated_id = matches[0].id
        if _link(store, marker_id, curated_id):
            report.edges_added += 1
        report.resolved.append((marker_id, curated_id))
    return report


def _link(store: KnowledgeStore, marker_id: str, curated_id: str) -> bool:
    """Add the weak marker↔curated edge unless it already exists (idempotent)."""
    existing = store.edges(marker_id, relation=RESOLUTION_RELATION.value, direction="any")
    if any(edge.target_id == curated_id for edge in existing):
        return False
    store.add_interaction(
        Interaction(
            source_id=marker_id,
            target_id=curated_id,
            relation=RESOLUTION_RELATION,
            confidence=RESOLUTION_CONFIDENCE,
            evidence=[
                f"review_status:{REVIEW_STATUS}",
                "resolution:exact_name_match",
                f"lit_marker:{marker_id}",
                f"curated:{curated_id}",
            ],
        )
    )
    return True
