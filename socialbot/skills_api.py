"""Voice + desktop skill API routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request
from pydantic import BaseModel


class SkillBody(BaseModel):
    text: str = ""


def register_skills_routes(app, state: dict) -> None:
    @app.get("/api/voice/status")
    def voice_status(request: Request):
        from .voice import VoiceEngine
        return VoiceEngine(store=state["store"]).capabilities()

    @app.post("/api/skills/run")
    def skills_run(body: SkillBody, request: Request):
        from .desktop_skills import DesktopSkills
        return DesktopSkills().run(body.text, store=state["store"])
