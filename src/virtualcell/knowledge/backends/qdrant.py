"""Qdrant vector backend for semantic / literature search (interface / skeleton).

Provides embedding-based retrieval over entity text. Implementation lands in a
subsequent release; the embedding function is intentionally pluggable.
"""

from __future__ import annotations

from collections.abc import Callable

from virtualcell.knowledge.schema import BioEntity

Embedder = Callable[[str], list[float]]


class QdrantVectorIndex:
    """Semantic index over entity text, backed by Qdrant.

    Install with the ``vector`` extra: ``pip install "virtualcell[vector]"``.
    """

    def __init__(self, url: str | None = None, embedder: Embedder | None = None) -> None:
        from virtualcell.core.config import get_settings

        self._url = url or get_settings().qdrant_url
        self._embedder = embedder
        self._client = None  # created lazily

    def index(self, entity: BioEntity) -> None:  # pragma: no cover
        raise NotImplementedError("Qdrant backend lands in a subsequent release")

    def search(self, query: str, k: int = 10) -> list[BioEntity]:  # pragma: no cover
        raise NotImplementedError("Qdrant backend lands in a subsequent release")
