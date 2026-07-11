"""FastAPI application entry point.

Run with: ``uvicorn virtualcell.api.main:app --reload``.

The app seeds an in-memory knowledge base with the bundled sample dataset at
startup so the knowledge endpoints are usable immediately.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from virtualcell import __version__
from virtualcell.api.routes import agents, knowledge, reasoning
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource


@asynccontextmanager
async def lifespan(app: FastAPI):
    from virtualcell.core.config import get_settings

    graph_path = get_settings().graph_path
    if graph_path:
        from virtualcell.knowledge.persistence import load_store

        store = load_store(graph_path)
    else:
        from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

        store = InMemoryKnowledgeStore()
        load_into(SampleDataSource(), store)
        # Also seed the immortalization graph so the mechanism/hypothesis reports of
        # the ImmortalizationAssessmentAgent can be grounded via the API.
        load_into(ImmortalizationSeedSource(), store)
    app.state.knowledge_store = store
    yield


app = FastAPI(
    title="Virtual Cell Reasoning Platform",
    version=__version__,
    description="An AI-driven, modular, explainable cell-biology reasoning platform.",
    lifespan=lifespan,
)

app.include_router(knowledge.router)
app.include_router(agents.router)
app.include_router(reasoning.router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok", "version": __version__}
