"""Facebook Pages — Graph API feed & photo posting, delete, basic metrics."""
from __future__ import annotations

from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

GRAPH = "https://graph.facebook.com/v21.0"


@register
class Facebook(Platform):
    name = "facebook"
    display_name = "Facebook Page"
    color = "#1877F2"
    icon = "📘"
    capabilities = {"post", "delete", "metrics"}
    max_length = 63206
    site = "https://facebook.com"
    docs_url = "https://developers.facebook.com/docs/pages-api/posts"
    auth_fields = [
        {"key": "page_id", "label": "Page ID", "required": True, "secret": False},
        {"key": "access_token", "label": "Page access token", "required": True, "secret": True,
         "help": "pages_manage_posts, pages_read_engagement permissions"},
    ]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}"}

    def publish(self, post: Post) -> PublishResult:
        page = self.require("page_id")
        text = post.effective_text()
        try:
            if post.media and post.media[0].startswith("http"):
                data = self.http.post_json(
                    f"{GRAPH}/{page}/photos",
                    params={"url": post.media[0], "caption": text[:5000]},
                    headers=self._headers())
                pid = data.get("post_id") or data.get("id", "")
            else:
                data = self.http.post_json(f"{GRAPH}/{page}/feed",
                                           params={"message": text}, headers=self._headers())
                pid = data.get("id", "")
        except Exception as exc:
            raise PlatformError(f"facebook post failed: {exc}") from exc
        return PublishResult(platform=self.name, ok=True, remote_id=pid,
                             url=f"https://facebook.com/{pid}")

    def delete(self, remote_id: str) -> bool:
        self.http.delete_json(f"{GRAPH}/{remote_id}", headers=self._headers())
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        data = self.http.get_json(
            f"{GRAPH}/{remote_id}",
            params={"fields": "likes.summary(true).limit(0),comments.summary(true).limit(0),"
                              "shares,reactions.limit(0).summary(true)"},
            headers=self._headers())
        likes = data.get("likes", {}).get("summary", {}).get("total_count", 0)
        reactions = data.get("reactions", {}).get("summary", {}).get("total_count", likes)
        return {"likes": likes, "reactions": reactions,
                "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
                "shares": (data.get("shares") or {}).get("count", 0)}
