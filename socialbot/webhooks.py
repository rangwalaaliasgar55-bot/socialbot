"""Outgoing webhooks — notify your own systems (n8n, Zapier, Make, Slack) when
a post is published."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from .models import Post, dumps

log = logging.getLogger("socialbot.webhooks")
DEFAULT_HOOK = os.environ.get("SOCIALBOT_WEBHOOK_URL")


def _payload(post: Post) -> dict:
    return {
        "event": "post.published",
        "post_id": post.id,
        "status": post.status,
        "platforms": post.platforms,
        "text": post.text,
        "tag": post.tag,
        "published_at": post.published_at,
        "results": post.results,
    }


def fire_webhook(url: Optional[str], post: Post) -> bool:
    """POST the publish payload to *url* (or the global default). Never raises."""
    target = url or DEFAULT_HOOK
    if not target:
        return False
    try:
        resp = requests.post(target, data=dumps(_payload(post)),
                             headers={"Content-Type": "application/json"}, timeout=15)
        ok = resp.status_code < 400
        log.info("webhook %s -> %s", target, "ok" if ok else f"HTTP {resp.status_code}")
        return ok
    except Exception as exc:
        log.warning("webhook %s failed: %s", target, exc)
        return False
