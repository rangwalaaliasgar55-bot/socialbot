"""Pinterest — create pins from an image URL via the v5 API."""
from __future__ import annotations

from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, guess_description, register

API = "https://api.pinterest.com/v5"


@register
class Pinterest(Platform):
    name = "pinterest"
    display_name = "Pinterest"
    color = "#E60023"
    icon = "📍"
    capabilities = {"post", "delete"}
    max_length = 500
    site = "https://pinterest.com"
    docs_url = "https://developers.pinterest.com/docs/api/v5/pins-create/"
    auth_fields = [
        {"key": "access_token", "label": "Access token", "required": True, "secret": True,
         "help": "pins:write, boards:read scopes"},
        {"key": "board_id", "label": "Board id", "required": True, "secret": False,
         "help": "from GET /v5/boards"},
    ]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}"}

    def publish(self, post: Post) -> PublishResult:
        image = next((m for m in post.media if m.startswith("http")), None)
        if not image:
            raise PlatformError("pinterest requires a public image URL in post media")
        payload = {
            "board_id": self.require("board_id"),
            "description": guess_description(post)[:500],
            "title": (post.text.strip().split("\n")[0] or "pin")[:100],
            "media_source": {"source_type": "image_url", "url": image}}
        try:
            data = self.http.post_json(f"{API}/pins", json=payload, headers=self._headers())
        except Exception as exc:
            raise PlatformError(f"pinterest pin failed: {exc}") from exc
        pid = data.get("id", "")
        return PublishResult(platform=self.name, ok=True, remote_id=pid,
                             url=f"https://pinterest.com/pin/{pid}")

    def delete(self, remote_id: str) -> bool:
        self.http.delete_json(f"{API}/pins/{remote_id}", headers=self._headers())
        return True
