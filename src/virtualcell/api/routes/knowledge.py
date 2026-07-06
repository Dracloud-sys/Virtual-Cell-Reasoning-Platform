"""Knowledge base API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from virtualcell.knowledge.schema import BioEntity

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _store(request: Request):
    return request.app.state.knowledge_store


@router.get("/search", response_model=list[BioEntity])
async def search(
    request: Request,
    q: str = Query(..., description="Search query over entity name/alias/description"),
    k: int = Query(10, ge=1, le=100),
) -> list[BioEntity]:
    """Search the knowledge base."""
    return _store(request).search(q, k=k)


@router.get("/entity/{entity_id}", response_model=BioEntity)
async def get_entity(request: Request, entity_id: str) -> BioEntity:
    """Fetch a single entity by id."""
    entity = _store(request).get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")
    return entity


@router.get("/entity/{entity_id}/neighbors", response_model=list[BioEntity])
async def neighbors(
    request: Request,
    entity_id: str,
    relation: str | None = Query(None),
) -> list[BioEntity]:
    """Return entities directly connected to ``entity_id``."""
    if _store(request).get(entity_id) is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")
    return _store(request).neighbors(entity_id, relation=relation)
