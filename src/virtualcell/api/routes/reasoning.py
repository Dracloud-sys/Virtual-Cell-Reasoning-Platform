"""Natural-language reasoning API routes.

``POST /reasoning/query`` is the platform's domain-neutral entry point: it accepts a
:class:`ReasoningQuery`, runs it through the same :class:`ReasoningService` the CLI uses,
and returns a :class:`ReasoningResponse`. The route contains no domain knowledge — a new
domain pack becomes reachable here without touching this file.

The pre-existing ``/reasoning/qa`` and ``/reasoning/explain`` routes are unchanged and
remain supported.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from virtualcell.platform.bootstrap import default_registry
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.domains import (
    QueryValidationError,
    UnknownDomainError,
    UnsupportedTaskError,
)
from virtualcell.platform.service import ReasoningService
from virtualcell.reasoning.explain import Explanation, explain
from virtualcell.reasoning.qa import Answer, QuestionAnswerer

router = APIRouter(prefix="/reasoning", tags=["reasoning"])

_REGISTRY = default_registry()


class QARequest(BaseModel):
    question: str
    k: int = 5


@router.post("/query", response_model=ReasoningResponse)
async def reasoning_query(request: Request, body: ReasoningQuery) -> ReasoningResponse:
    """Run a domain-neutral reasoning query through the platform boundary.

    Failure modes are reported distinctly and structurally: an unregistered domain is
    404, an unsupported task or an invalid domain payload is 422. A *provider* failure is
    not an HTTP error — the scientific response is still returned, with the outcome
    recorded in ``literature.status`` so it can never be mistaken for evidence.
    """
    service = ReasoningService(request.app.state.knowledge_store, _REGISTRY)
    try:
        return await service.query(body)
    except UnknownDomainError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_domain",
                "message": str(exc),
                "available_domains": _REGISTRY.domains(),
            },
        ) from exc
    except UnsupportedTaskError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_task",
                "message": str(exc),
                "supported_tasks": _REGISTRY.tasks(body.domain),
            },
        ) from exc
    except QueryValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_query", "message": str(exc)},
        ) from exc


@router.get("/domains")
async def list_domains() -> dict[str, dict[str, list[str]]]:
    """Registered domains and the tasks each supports."""
    return {"domains": {name: _REGISTRY.tasks(name) for name in _REGISTRY.domains()}}


@router.post("/qa", response_model=Answer)
async def qa(request: Request, body: QARequest) -> Answer:
    """Answer a natural-language question, grounded in the knowledge graph."""
    store = request.app.state.knowledge_store
    return QuestionAnswerer(store).answer(body.question, k=body.k)


@router.get("/explain/{entity_id}", response_model=Explanation)
async def explain_entity(
    request: Request,
    entity_id: str,
    hops: int = Query(2, ge=1, le=4),
    k: int = Query(25, ge=1, le=200),
) -> Explanation:
    """Return the evidence-graded mechanistic reach of an entity."""
    store = request.app.state.knowledge_store
    try:
        return explain(store, entity_id, max_hops=hops, top_k=k)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
