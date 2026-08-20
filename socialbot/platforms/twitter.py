"""X (Twitter) — API v2 posting, delete, metrics, like/follow + recent search."""
from __future__ import annotations

from typing import Any, Dict, List

from ..http import HttpError
from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

API = "https://api.x.com/2"


@register
class Twitter(Platform):
    name = "twitter"
    display_name = "X (Twitter)"
    color = "#1d9bf0"
    icon = "𝕏"
    capabilities = {"post", "delete", "metrics", "like", "follow", "search"}
    max_length = 280
    site = "https://x.com"
    docs_url = "https://docs.x.com/x-api/"
    auth_fields = [
        {"key": "access_token", "label": "User access token", "required": True, "secret": True,
         "help": "OAuth 2.0 user context token (scope tweet.read tweet.write)"},
        {"key": "refresh_token", "label": "Refresh token", "required": False, "secret": True},
        {"key": "client_id", "label": "OAuth2 client id", "required": False, "secret": True},
        {"key": "client_secret", "label": "OAuth2 client secret", "required": False, "secret": True},
        {"key": "user_id", "label": "Your user id", "required": False, "secret": False,
         "help": "Needed for like/follow bot actions"},
    ]
    guide = [
        "Go to developer.x.com and sign in with your X account.",
        "Create a Project and an App inside it (the free tier is enough).",
        "Open your app → 'User authentication settings' → Enable OAuth 2.0 (Web App).",
        "Add the redirect URL: http://localhost:8000/api/accounts/twitter/oauth/callback "
        "(use your dashboard's port if it differs).",
        "In 'App permissions' tick Read, Write — and note the Client ID and Client Secret.",
        "Easiest path: paste the Client ID + Client Secret in the fields and click "
        "'Connect with X' — SocialBot handles authorization, tokens and auto-refresh.",
        "Or generate a 'User access token' (scopes: tweet.read tweet.write users.read "
        "like.write follows.write offline.access) and paste it manually with your user id.",
    ]
    oauth = {
        "provider": "X",
        "auth_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.x.com/2/oauth2/token",
        "scope": "tweet.read tweet.write users.read like.write follows.write offline.access",
        "client_id_key": "client_id",
        "client_secret_key": "client_secret",
        "pkce": True,
    }

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}"}

    def _maybe_refresh(self) -> None:
        """Refresh an OAuth2 user token using the refresh_token grant."""
        refresh = self.setting("refresh_token")
        client_id = self.setting("client_id")
        if not (refresh and client_id):
            return
        try:
            data = self.http.post_json(
                "https://api.x.com/2/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "refresh_token", "refresh_token": refresh,
                      "client_id": client_id})
            if isinstance(data, dict) and data.get("access_token"):
                self.config["access_token"] = data["access_token"]
                if data.get("refresh_token"):
                    self.config["refresh_token"] = data["refresh_token"]
        except Exception:
            pass

    def verify(self) -> tuple:
        try:
            me = self.http.get_json(f"{API}/users/me", params={"user.fields": "username"},
                                    headers=self._headers())
            username = me.get("data", {}).get("username")
            self.config.setdefault("user_id", me.get("data", {}).get("id"))
            return True, f"authenticated as @{username}"
        except Exception as exc:
            return False, str(exc)

    def publish(self, post: Post) -> PublishResult:
        text = post.effective_text()
        if len(text) > self.max_length:
            text = text[: self.max_length - 1] + "…"
        payload: Dict[str, Any] = {"text": text}
        if post.media:
            raise PlatformError(
                "X media upload requires the v1.1 media endpoint (OAuth 1.0a) — "
                "media is not supported for X yet; use text or another platform")
        try:
            data = self.http.post_json(f"{API}/tweets", json=payload, headers=self._headers())
        except HttpError as exc:
            if exc.status == 401:
                self._maybe_refresh()
                data = self.http.post_json(f"{API}/tweets", json=payload, headers=self._headers())
            else:
                raise PlatformError(f"X post failed: {exc}") from exc
        tid = data.get("data", {}).get("id", "")
        return PublishResult(platform=self.name, ok=True, remote_id=tid,
                             url=f"https://x.com/i/web/status/{tid}")

    def delete(self, remote_id: str) -> bool:
        self.http.delete_json(f"{API}/tweets/{remote_id}", headers=self._headers())
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        data = self.http.get_json(
            f"{API}/tweets/{remote_id}", params={"tweet.fields": "public_metrics"},
            headers=self._headers())
        m = data.get("data", {}).get("public_metrics", {})
        return {"likes": m.get("like_count", 0), "shares": m.get("retweet_count", 0),
                "comments": m.get("reply_count", 0), "impressions": m.get("impression_count", 0)}

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        data = self.http.get_json(
            f"{API}/tweets/search/recent",
            params={"query": query, "max_results": max(10, min(limit, 100)),
                    "tweet.fields": "author_id,text"},
            headers=self._headers())
        out = []
        for t in data.get("data", [])[:limit]:
            out.append({"id": t.get("id"), "author_id": t.get("author_id", ""),
                        "text": (t.get("text") or "")[:300],
                        "url": f"https://x.com/i/web/status/{t.get('id')}"})
        return out

    def like(self, item: Dict[str, Any]) -> bool:
        user_id = self.setting("user_id")
        if not user_id:
            raise PlatformError("X like requires your 'user_id' setting")
        self.http.put_json(f"{API}/users/{user_id}/likes/{item['id']}", json={}, headers=self._headers())
        return True

    def follow(self, item: Dict[str, Any]) -> bool:
        user_id = self.setting("user_id")
        if not user_id:
            raise PlatformError("X follow requires your 'user_id' setting")
        target = item.get("author_id")
        if not target:
            raise PlatformError("no target author id to follow")
        self.http.put_json(f"{API}/users/{user_id}/following/{target}", json={}, headers=self._headers())
        return True
