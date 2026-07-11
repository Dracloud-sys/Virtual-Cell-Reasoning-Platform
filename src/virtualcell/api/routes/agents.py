"""Agent execution API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

import virtualcell.agents  # noqa: F401  (registers agents on import)
from virtualcell.core.agent import AgentContext
from virtualcell.core.contracts import AgentInput, AgentOutput
from virtualcell.core.registry import registry

router = APIRouter(prefix="/agents", tags=["agents"])


class RunRequest(BaseModel):
    query: str
    context: dict = {}


@router.get("")
async def list_agents() -> dict[str, list[str]]:
    """List registered agent names."""
    return {"agents": registry.names()}


@router.post("/{name}/run", response_model=AgentOutput)
async def run_agent(request: Request, name: str, body: RunRequest) -> AgentOutput:
    """Run a named agent against a query."""
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"unknown agent: {name}")
    context = AgentContext(services={"knowledge_store": request.app.state.knowledge_store})
    agent = registry.create(name, context)
    try:
        return await agent.run(AgentInput(query=body.query, context=body.context))
    except (ValueError, ValidationError) as exc:
        # Bad/insufficient input (e.g. missing intent, invalid marker, unsupported
        # intent/construct) is a client error, not a server error.
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_assessment_input", "message": str(exc)},
        ) from exc
