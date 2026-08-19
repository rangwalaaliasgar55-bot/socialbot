"""Discord — publish via incoming webhooks (channels, with embeds for media)."""
from __future__ import annotations

from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register


@register
class Discord(Platform):
    name = "discord"
    display_name = "Discord"
    color = "#5865F2"
    icon = "💬"
    capabilities = {"post"}
    max_length = 2000
    site = "https://discord.com"
    docs_url = "https://discord.com/developers/docs/resources/webhook"
    auth_fields = [
        {"key": "webhook_url", "label": "Webhook URL", "required": True, "secret": True,
         "help": "Server Settings → Integrations → Webhooks → Copy URL"},
        {"key": "username", "label": "Override bot username", "required": False, "secret": False},
    ]

    def publish(self, post: Post) -> PublishResult:
        url = self.require("webhook_url")
        text = post.effective_text()[:2000]
        payload: Dict[str, Any] = {"content": text}
        if self.setting("username"):
            payload["username"] = self.setting("username")
        if post.media:
            payload["embeds"] = [{"image": {"url": m}} for m in post.media[:4] if m.startswith("http")]
        try:
            resp = self.http.session.post(url, json=payload, timeout=self.http.timeout)
        except Exception as exc:
            raise PlatformError(f"discord webhook failed: {exc}") from exc
        if resp.status_code >= 400:
            raise PlatformError(f"discord webhook: HTTP {resp.status_code} {resp.text[:200]}")
        return PublishResult(platform=self.name, ok=True, remote_id="",
                             url="https://discord.com/channels/@me")
