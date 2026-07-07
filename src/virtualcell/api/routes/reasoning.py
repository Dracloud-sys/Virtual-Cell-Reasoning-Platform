"""Natural-language reasoning API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from virtualcell.reasoning.explain import Explanation, explain
from virtualcell.reasoning.qa import Answer, QuestionAnswerer

router = APIRouter(prefix="/reasoning", tags=["reasoning"])


class QARequest(BaseModel):
    question: str
    k: int = 5


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
