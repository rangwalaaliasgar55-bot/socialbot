"""Threads — container + publish flow via the Threads API."""
from __future__ import annotations

from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

API = "https://graph.threads.net/v1.0"


@register
class Threads(Platform):
    name = "threads"
    display_name = "Threads"
    color = "#000000"
    icon = "🧵"
    capabilities = {"post", "metrics"}
    max_length = 500
    site = "https://threads.com"
    docs_url = "https://developers.facebook.com/docs/threads/posts"
    auth_fields = [
        {"key": "user_id", "label": "Threads user id", "required": True, "secret": False},
        {"key": "access_token", "label": "Access token", "required": True, "secret": True,
         "help": "threads_basic + threads_content_publish scopes"},
    ]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}"}

    def publish(self, post: Post) -> PublishResult:
        user = self.require("user_id")
        text = post.effective_text()[:500]
        image = next((m for m in post.media if m.startswith("http")), None)
        params: Dict[str, Any] = {"text": text, "media_type": "IMAGE" if image else "TEXT"}
        if image:
            params["image_url"] = image
        try:
            container = self.http.post_json(f"{API}/{user}/threads", params=params,
                                            headers=self._headers())
            creation_id = container.get("id")
            if not creation_id:
                raise PlatformError(f"threads container failed: {container}")
            published = self.http.post_json(f"{API}/{user}/threads_publish",
                                            params={"creation_id": creation_id},
                                            headers=self._headers())
        except PlatformError:
            raise
        except Exception as exc:
            raise PlatformError(f"threads publish failed: {exc}") from exc
        pid = published.get("id", "")
        return PublishResult(platform=self.name, ok=True, remote_id=pid)

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        data = self.http.get_json(f"{API}/{remote_id}",
                                  params={"fields": "views,replies,likes,reposts,quotes"},
                                  headers=self._headers())
        return {"likes": data.get("likes", 0), "shares": data.get("reposts", 0),
                "comments": data.get("replies", 0), "impressions": data.get("views", 0)}
