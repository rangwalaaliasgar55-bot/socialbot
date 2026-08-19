"""Slack — publish via incoming webhooks."""
from __future__ import annotations

from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register


@register
class Slack(Platform):
    name = "slack"
    display_name = "Slack"
    color = "#4A154B"
    icon = "🏢"
    capabilities = {"post"}
    max_length = 40000
    site = "https://slack.com"
    docs_url = "https://api.slack.com/messaging/webhooks"
    auth_fields = [
        {"key": "webhook_url", "label": "Incoming webhook URL", "required": True, "secret": True,
         "help": "api.slack.com/messaging/webhooks"},
    ]

    def publish(self, post: Post) -> PublishResult:
        url = self.require("webhook_url")
        payload: Dict[str, Any] = {"text": post.effective_text()}
        if post.media:
            payload["blocks"] = [{"type": "image",
                                  "image_url": m, "alt_text": "attachment"}
                                 for m in post.media if m.startswith("http")]
        try:
            resp = self.http.session.post(url, json=payload, timeout=self.http.timeout)
        except Exception as exc:
            raise PlatformError(f"slack webhook failed: {exc}") from exc
        if resp.status_code >= 400 or resp.text.strip() != "ok":
            raise PlatformError(f"slack webhook: {resp.text[:200]}")
        return PublishResult(platform=self.name, ok=True)
