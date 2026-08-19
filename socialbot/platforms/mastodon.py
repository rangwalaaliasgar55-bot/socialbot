"""Mastodon — full support: post, media, delete, metrics, favourite/reblog/follow, search."""
from __future__ import annotations

from typing import Any, Dict, List

from ..models import Post, PublishResult
from .base import Platform, PlatformError, download_media, register


@register
class Mastodon(Platform):
    name = "mastodon"
    display_name = "Mastodon"
    color = "#6364FF"
    icon = "🐘"
    capabilities = {"post", "delete", "metrics", "like", "repost", "comment", "follow", "search"}
    max_length = 500
    site = "https://joinmastodon.org"
    docs_url = "https://docs.joinmastodon.org/methods/statuses/"
    auth_fields = [
        {"key": "instance", "label": "Instance URL", "required": True, "secret": False,
         "help": "e.g. https://mastodon.social"},
        {"key": "access_token", "label": "Access token", "required": True, "secret": True,
         "help": "Preferences → Development → New application → write:statuses scope"},
    ]

    def _api(self) -> str:
        instance = str(self.require("instance")).rstrip("/")
        return f"{instance}/api/v1"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}"}

    def verify(self) -> tuple:
        try:
            me = self.http.get_json(f"{self._api()}/accounts/verify_credentials",
                                    headers=self._headers())
            return True, f"@{me.get('username')}@{me.get('acct', '')} authenticated"
        except Exception as exc:
            return False, str(exc)

    def publish(self, post: Post) -> PublishResult:
        text = post.effective_text()
        if self.max_length and len(text) > self.max_length:
            text = text[: self.max_length - 1] + "…"
        media_ids: List[str] = []
        for m in post.media[:4]:
            try:
                content, mime = download_media(m, self.http)
                files = {"file": (m.split("/")[-1] or "media", content, mime)}
                resp = self.http.session.post(f"{self._api()}/media",
                                              headers=self._headers(), files=files,
                                              timeout=self.http.timeout)
                if resp.status_code >= 400:
                    raise PlatformError(resp.text[:200])
                media_ids.append(resp.json()["id"])
            except PlatformError:
                raise
            except Exception as exc:
                raise PlatformError(f"mastodon media upload failed: {exc}") from exc
        payload: Dict[str, Any] = {"status": text}
        if media_ids:
            payload["media_ids"] = media_ids
        try:
            status = self.http.post_json(f"{self._api()}/statuses", json=payload,
                                         headers=self._headers())
        except Exception as exc:
            raise PlatformError(f"mastodon post failed: {exc}") from exc
        return PublishResult(platform=self.name, ok=True, remote_id=status.get("id", ""),
                             url=status.get("url", ""))

    def delete(self, remote_id: str) -> bool:
        self.http.delete_json(f"{self._api()}/statuses/{remote_id}", headers=self._headers())
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        s = self.http.get_json(f"{self._api()}/statuses/{remote_id}", headers=self._headers())
        return {"likes": s.get("favourites_count", 0), "shares": s.get("reblogs_count", 0),
                "comments": s.get("replies_count", 0)}

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        instance = str(self.require("instance")).rstrip("/")
        data = self.http.get_json(
            f"{instance}/api/v2/search",
            params={"q": query, "type": "statuses", "limit": limit, "resolve": "true"},
            headers=self._headers())
        out = []
        for s in data.get("statuses", [])[:limit]:
            acct = s.get("account", {})
            out.append({"id": s.get("id"), "author": acct.get("acct", ""),
                        "author_id": acct.get("id"), "text": s.get("content", "")[:300],
                        "url": s.get("url", "")})
        return out

    def like(self, item: Dict[str, Any]) -> bool:
        self.http.post_json(f"{self._api()}/statuses/{item['id']}/favourite", json={},
                            headers=self._headers())
        return True

    def repost(self, item: Dict[str, Any]) -> bool:
        self.http.post_json(f"{self._api()}/statuses/{item['id']}/reblog", json={},
                            headers=self._headers())
        return True

    def follow(self, item: Dict[str, Any]) -> bool:
        account_id = item.get("author_id")
        if not account_id:
            raise PlatformError("no account id available for follow (run a search first)")
        self.http.post_json(f"{self._api()}/accounts/{account_id}/follow", json={},
                            headers=self._headers())
        return True

    def comment(self, item: Dict[str, Any], text: str) -> bool:
        self.http.post_json(f"{self._api()}/statuses", json={"status": text,
                                                             "in_reply_to_id": item["id"]},
                            headers=self._headers())
        return True
