"""Integration tests for the FastAPI app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from virtualcell.api.main import app


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_knowledge_search() -> None:
    with TestClient(app) as client:
        resp = client.get("/knowledge/search", params={"q": "p53"})
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


def test_agent_run() -> None:
    with TestClient(app) as client:
        resp = client.post("/agents/literature/run", json={"query": "TP53"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "literature"
        assert body["claims"]


def test_reasoning_qa(monkeypatch) -> None:
    # Force the offline backend so the test never makes a network call.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(app) as client:
        resp = client.post("/reasoning/qa", json={"question": "What is TP53?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["backend"] == "offline-template"
        assert body["grounded_entity_ids"]
        assert body["facts"]
