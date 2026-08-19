"""Instagram Business — two-step container + publish flow via the Graph API."""
from __future__ import annotations

from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

GRAPH = "https://graph.facebook.com/v21.0"


@register
class Instagram(Platform):
    name = "instagram"
    display_name = "Instagram"
    color = "#E1306C"
    icon = "📸"
    capabilities = {"post", "delete", "metrics"}
    max_length = 2200
    site = "https://instagram.com"
    docs_url = "https://developers.facebook.com/docs/instagram-api/guides/content-publishing"
    auth_fields = [
        {"key": "user_id", "label": "IG Business user id", "required": True, "secret": False,
         "help": "Instagram Business account id (linked to a FB page)"},
        {"key": "access_token", "label": "Access token", "required": True, "secret": True,
         "help": "instagram_content_publish permission"},
    ]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}"}

    def publish(self, post: Post) -> PublishResult:
        user = self.require("user_id")
        caption = post.effective_text()[:2200]
        image = next((m for m in post.media if m.startswith("http")), None)
        if not image:
            raise PlatformError("instagram requires a public image URL in post media")
        try:
            container = self.http.post_json(
                f"{GRAPH}/{user}/media",
                params={"image_url": image, "caption": caption}, headers=self._headers())
            creation_id = container.get("id")
            if not creation_id:
                raise PlatformError(f"instagram container failed: {container}")
            published = self.http.post_json(f"{GRAPH}/{user}/media_publish",
                                            params={"creation_id": creation_id},
                                            headers=self._headers())
        except PlatformError:
            raise
        except Exception as exc:
            raise PlatformError(f"instagram publish failed: {exc}") from exc
        media_id = published.get("id", "")
        return PublishResult(platform=self.name, ok=True, remote_id=media_id)

    def delete(self, remote_id: str) -> bool:
        self.http.delete_json(f"{GRAPH}/{remote_id}", headers=self._headers())
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        data = self.http.get_json(f"{GRAPH}/{remote_id}",
                                  params={"fields": "like_count,comments_count"},
                                  headers=self._headers())
        return {"likes": data.get("like_count", 0), "comments": data.get("comments_count", 0)}
