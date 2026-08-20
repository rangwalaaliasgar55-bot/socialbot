"""Telegram — publish via the official Bot API (sendMessage / sendPhoto)."""
from __future__ import annotations

import requests
from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

API = "https://api.telegram.org"


@register
class Telegram(Platform):
    name = "telegram"
    display_name = "Telegram"
    color = "#2AABEE"
    icon = "✈️"
    capabilities = {"post"}
    max_length = 4096
    site = "https://telegram.org"
    docs_url = "https://core.telegram.org/bots/api"
    auth_fields = [
        {"key": "bot_token", "label": "Bot token", "required": True, "secret": True,
         "help": "From @BotFather"},
        {"key": "chat_id", "label": "Chat / channel ID", "required": True, "secret": False,
         "help": "e.g. -1001234567890 for a channel or your numeric user id"},
    ]
    guide = [
        "Open Telegram and start a chat with @BotFather (the official bot that creates bots).",
        "Send the command /newbot and follow the prompts — pick a display name and a username ending in 'bot'.",
        "BotFather replies with your bot token (looks like 123456789:AAH...). Copy it.",
        "If you want posts to land in a channel: add your bot to that channel as an ADMIN.",
        "Send any message to your bot (or channel), then open "
        "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates in your browser.",
        "Copy the numeric chat id from \"chat\":{\"id\": ...} — channels have ids like -1001234567890.",
        "Paste the bot token and chat id here, then click Save.",
    ]

    def _call(self, method: str, payload: Dict[str, Any], files=None) -> Dict[str, Any]:
        token = self.require("bot_token")
        resp = self.http.session.post(f"{API}/bot{token}/{method}",
                                      json=payload if files is None else None,
                                      data=payload if files else None, files=files,
                                      timeout=self.http.timeout)
        body = resp.json() if resp.content else {}
        if not resp.ok or not body.get("ok"):
            raise PlatformError(f"telegram {method}: {body.get('description', resp.text[:200])}")
        return body["result"]

    def verify(self) -> tuple:
        try:
            me = self._call("getMe", {})
            return True, f"bot @{me.get('username', '?')} ready"
        except PlatformError as exc:
            return False, str(exc)
        except Exception as exc:  # pragma: no cover
            return False, str(exc)

    def publish(self, post: Post) -> PublishResult:
        chat = self.require("chat_id")
        text = post.effective_text()
        media = [m for m in post.media if m]

        message = None
        if media:
            first = media[0]
            method, key = ("sendPhoto", "photo")
            if first.lower().split("?")[0].endswith((".mp4",)):
                method, key = ("sendVideo", "video")
            payload: Dict[str, Any] = {"chat_id": chat, "caption": text[:1024]}
            if first.startswith(("http://", "https://")):
                payload[key] = first
                message = self._call(method, payload)
            else:  # local file upload
                with open(first, "rb") as fh:
                    message = self._call(method, payload, files={key: fh})
        if message is None:
            message = self._call("sendMessage", {"chat_id": chat, "text": text})

        username = str(message.get("chat", {}).get("username", "c"))
        return PublishResult(
            platform=self.name, ok=True, remote_id=str(message.get("message_id")),
            url=f"https://t.me/{username}/{message.get('message_id')}")
