"""Natural-language reasoning API routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

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
