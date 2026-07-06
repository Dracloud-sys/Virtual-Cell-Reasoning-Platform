"""Neo4j KnowledgeStore backend (interface / skeleton).

Graph-native storage for relationship-heavy queries. The methods raise
``NotImplementedError`` in v0.1; the class documents the intended Cypher-backed
implementation and keeps the driver import lazy so the package works without the
``graph`` extra installed.
"""

from __future__ import annotations

from virtualcell.knowledge.schema import BioEntity, Interaction


class Neo4jKnowledgeStore:
    """KnowledgeStore backed by a Neo4j graph database.

    Install with the ``graph`` extra: ``pip install "virtualcell[graph]"``.
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        from virtualcell.core.config import get_settings

        settings = get_settings()
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self._driver = None  # created lazily in _connect()

    def _connect(self):  # pragma: no cover - requires a live database
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "neo4j driver not installed; install with the 'graph' extra"
                ) from exc
            self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
        return self._driver

    def upsert(self, entity: BioEntity) -> None:  # pragma: no cover
        raise NotImplementedError("Neo4j backend lands in a subsequent release")

    def add_interaction(self, interaction: Interaction) -> None:  # pragma: no cover
        raise NotImplementedError("Neo4j backend lands in a subsequent release")

    def get(self, entity_id: str) -> BioEntity | None:  # pragma: no cover
        raise NotImplementedError("Neo4j backend lands in a subsequent release")

    def neighbors(
        self, entity_id: str, relation: str | None = None
    ) -> list[BioEntity]:  # pragma: no cover  # noqa: E501
        raise NotImplementedError("Neo4j backend lands in a subsequent release")

    def search(self, query: str, k: int = 10) -> list[BioEntity]:  # pragma: no cover
        raise NotImplementedError("Neo4j backend lands in a subsequent release")
