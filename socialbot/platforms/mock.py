"""Mock platform — lets you develop and demo SocialBot with zero credentials.

Everything "works": posts get fake remote IDs and URLs, metrics tick upward,
and like/follow/comment/repost succeed. It also simulates a live social graph:
searchable posts by fake users, trending topics, and an inbox with realistic
DM intents — so every feature (including the background agents) can be demoed
end to end. Enable it by adding an account: ``socialbot accounts add mock``.
"""
from __future__ import annotations

import itertools
import random
from typing import Any, Dict, List

from ..models import Post, PublishResult
from .base import Platform, register

_counter = itertools.count(1)

TRENDING_TOPICS = [
    {"topic": "AI agents", "source": "mock-trending", "score": 98},
    {"topic": "open source", "source": "mock-trending", "score": 91},
    {"topic": "#python", "source": "mock-trending", "score": 87},
    {"topic": "content automation", "source": "mock-trending", "score": 84},
    {"topic": "indie hackers", "source": "mock-trending", "score": 79},
    {"topic": "#growth", "source": "mock-trending", "score": 74},
]

INBOX_INTENTS = [
    "How much does the pro plan cost? I saw pricing on your site.",
    "Can I get a demo of the scheduler this week?",
    "Thanks so much for the help, really appreciate it!",
    "This is broken, I want a refund please.",
    "Hi! Quick question about API limits.",
    "What's the best time to post on LinkedIn?",
    "Free money giveaway click here now!!!",
    "Do you offer a trial before subscribing?",
    "Love the product, keep up the great work!",
]


@register
class MockPlatform(Platform):
    name = "mock"
    display_name = "Mock (demo)"
    color = "#8b5cf6"
    icon = "🧪"
    capabilities = {"post", "delete", "metrics", "like", "follow", "comment", "repost",
                    "search", "quote", "thread", "trending", "inbox"}
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

    def quote(self, item: Dict[str, Any], text: str = "") -> bool:
        return True

    # ------------------------------------------------------- agents / inbox
    def get_trending(self, limit: int = 10) -> List[Dict[str, Any]]:
        return TRENDING_TOPICS[:limit]

    def list_messages(self, limit: int = 10) -> List[Dict[str, Any]]:
        n = next(_counter)
        msgs = []
        for i in range(1, min(limit, len(INBOX_INTENTS)) + 1):
            msgs.append({"id": f"msg_{n}_{i}", "author": f"user{i}",
                         "text": INBOX_INTENTS[(i + n) % len(INBOX_INTENTS)],
                         "ts": None})
        random.shuffle(msgs)
        return msgs

    def reply_message(self, message: Dict[str, Any], text: str) -> bool:
        return True