"""Mock platform — lets you develop and demo SocialBot with zero credentials.

Everything "works": posts get fake remote IDs and URLs, metrics tick upward,
and like/follow/comment succeed. Enable it by adding an account:
``socialbot accounts add mock``.
"""
from __future__ import annotations

import itertools
from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, register

_counter = itertools.count(1)


@register
class MockPlatform(Platform):
    name = "mock"
    display_name = "Mock (demo)"
    color = "#8b5cf6"
    icon = "🧪"
    capabilities = {"post", "delete", "metrics", "like", "follow", "comment", "repost", "search"}
    max_length = 5000
    site = "https://example.com"
    docs_url = "https://github.com/rangwalaaliasgar55-bot/socialbot"
    auth_fields = [
        {"key": "username", "label": "Mock username", "required": False, "secret": False},
    ]

    def publish(self, post: Post) -> PublishResult:
        n = next(_counter)
        remote_id = f"mock_{n}"
        return PublishResult(
            platform=self.name, ok=True, remote_id=remote_id,
            url=f"https://example.com/posts/{remote_id}")

    def delete(self, remote_id: str) -> bool:
        return remote_id.startswith("mock_")

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        n = next(_counter)
        return {"likes": n * 3 % 97, "shares": n * 5 % 53, "comments": n * 2 % 23,
                "impressions": n * 137 % 9973}

    def search(self, query: str, limit: int = 10) -> list:
        return [{"id": f"mock_{i}", "author": f"user{i}", "text": f"post about {query} #{i}",
                 "url": f"https://example.com/posts/mock_{i}"} for i in range(1, limit + 1)]

    def like(self, item: Dict[str, Any]) -> bool:
        return True

    def follow(self, item: Dict[str, Any]) -> bool:
        return True

    def comment(self, item: Dict[str, Any], text: str) -> bool:
        return True

    def repost(self, item: Dict[str, Any]) -> bool:
        return True
