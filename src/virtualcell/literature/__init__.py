"""Automated literature discovery, extraction and verification (PR8b+).

This package separates two things the platform must never conflate:

* **discovery** — finding and describing papers (metadata is *not* a biological
  claim); and
* **verified evidence** — a quantitative observation that has been checked against
  the source text and may become a canonical :class:`ExperimentRun`.

PR8b implements the discovery slice (contracts, a bounded open-access provider,
deterministic query building, deduplication and transparent relevance scoring).
Source-grounded extraction, deterministic verification, and canonical conversion
are later slices (their contracts are defined here so the bundle shape is stable).

Layering: this package depends only on ``core`` (never on ``agents``/``reasoning``).
It never writes to the KnowledgeStore — unreviewed literature must not become an
established graph edge.
"""
