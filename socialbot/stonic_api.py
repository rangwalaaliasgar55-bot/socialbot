"""Register Stonic command-center routes on the FastAPI app."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request


def register_stonic_routes(app, state: dict) -> None:
    @app.get("/api/stonic/core")
    def stonic_core(request: Request):
        from .agent_town import system_core
        return system_core(state["store"])

    @app.get("/api/stonic/agents")
    def stonic_agents(request: Request):
        from .agent_town import AgentTown
        return AgentTown(state["store"]).list_agents()

    @app.post("/api/stonic/agents/{agent_id}/assign")
    def stonic_assign(agent_id: str, request: Request, body: Optional[Dict[str, Any]] = None):
        from .agent_town import AgentTown
        task = (body or {}).get("task") or "stand by"
        return AgentTown(state["store"]).assign(agent_id, task)
