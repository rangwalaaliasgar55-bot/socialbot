"""Lemmy — federated link aggregator (create posts, comment, vote, search).

Uses the Lemmy HTTP API v3 with a JWT obtained via username/password login
(or a pre-supplied JWT). Works with any Lemmy instance (lemmy.world,
lemmy.ml, etc.).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register


@register
class Lemmy(Platform):
    name = "lemmy"
    display_name = "Lemmy"
    color = "#00C853"
    icon = "🍋"
    capabilities = {"post", "delete", "metrics", "like", "comment", "search"}
    max_length = 20000
    site = "https://join-lemmy.org"
    docs_url = "https://join-lemmy.org/docs/contributors/04-api.html"
    auth_fields = [
        {"key": "instance", "label": "Instance URL", "required": True, "secret": False,
         "help": "e.g. https://lemmy.world"},
        {"key": "username", "label": "Username (or email)", "required": False, "secret": False,
         "help": "Needed if you don't supply a JWT"},
        {"key": "password", "label": "Password", "required": False, "secret": True},
        {"key": "jwt", "label": "JWT (optional)", "required": False, "secret": True,
         "help": "Pre-obtained auth token; skips login"},
        {"key": "community", "label": "Default community name", "required": False, "secret": False,
         "help": "e.g. technology (without !)"},
        {"key": "community_id", "label": "Default community ID", "required": False, "secret": False,
         "help": "Numeric id; overrides community name if both set"},
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._jwt: Optional[str] = None

    def _api(self) -> str:
        instance = str(self.require("instance")).rstrip("/")
        return f"{instance}/api/v3"

    def _auth(self) -> str:
        if self._jwt:
            return self._jwt
        jwt = self.setting("jwt")
        if jwt:
            self._jwt = str(jwt)
            return self._jwt
        user = self.setting("username")
        password = self.setting("password")
        if not user or not password:
            raise PlatformError(
                "lemmy needs either 'jwt' or both 'username' + 'password'"
            )
        resp = self.http.session.post(
            f"{self._api()}/user/login",
            json={"username_or_email": user, "password": password},
            timeout=self.http.timeout,
        )
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "jwt" not in body:
            raise PlatformError(f"lemmy login failed: {body or resp.text[:200]}")
        self._jwt = body["jwt"]
        return self._jwt

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._auth()}"}

    def verify(self) -> tuple:
        try:
            me = self.http.session.get(
                f"{self._api()}/user/me",
                headers=self._headers(),
                timeout=self.http.timeout,
            )
            if me.status_code < 400:
                info = me.json().get("my_user", {}).get("local_user_view", {}).get("person", {})
                name = info.get("name") or info.get("display_name") or "?"
                return True, f"@{name} on {self.setting('instance')}"
            return True, f"connected to {self.setting('instance')}"
        except Exception as exc:
            return False, str(exc)

    def _resolve_community_id(self) -> int:
        cid = self.setting("community_id")
        if cid:
            return int(cid)
        name = self.setting("community")
        if not name:
            raise PlatformError(
                "no community configured — set 'community' or 'community_id' on the account"
            )
        name = str(name).lstrip("!")
        data = self.http.get_json(
            f"{self._api()}/community",
            params={"name": name},
            headers=self._headers(),
        )
        community = data.get("community_view", {}).get("community") or data.get("community")
        if not community:
            raise PlatformError(f"community '{name}' not found on this instance")
        return int(community["id"])

    def publish(self, post: Post) -> PublishResult:
        text = post.effective_text()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        title = (lines[0] if lines else "post")[:200]
        body = "\n".join(lines[1:]) if len(lines) > 1 else None

        link = next((m for m in post.media if m.startswith("http")), None)
        payload: Dict[str, Any] = {
            "name": title,
            "community_id": self._resolve_community_id(),
        }
        if body:
            payload["body"] = body
        if link:
            payload["url"] = link

        resp = self.http.session.post(
            f"{self._api()}/post",
            json=payload,
            headers=self._headers(),
            timeout=self.http.timeout,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise PlatformError(f"lemmy create post: {data or resp.text[:200]}")
        post_view = data.get("post_view", {}).get("post") or data.get("post") or {}
        pid = post_view.get("id")
        ap_id = post_view.get("ap_id") or ""
        instance = str(self.setting("instance")).rstrip("/")
        url = ap_id or (f"{instance}/post/{pid}" if pid else None)
        return PublishResult(platform=self.name, ok=True, remote_id=str(pid or ""), url=url)

    def delete(self, remote_id: str) -> bool:
        resp = self.http.session.post(
            f"{self._api()}/post/delete",
            json={"post_id": int(remote_id), "deleted": True},
            headers=self._headers(),
            timeout=self.http.timeout,
        )
        if resp.status_code >= 400:
            raise PlatformError(f"lemmy delete: {resp.text[:200]}")
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        data = self.http.get_json(
            f"{self._api()}/post",
            params={"id": int(remote_id)},
            headers=self._headers(),
        )
        counts = data.get("post_view", {}).get("counts") or {}
        return {
            "likes": counts.get("score", 0),
            "upvotes": counts.get("upvotes", 0),
            "downvotes": counts.get("downvotes", 0),
            "comments": counts.get("comments", 0),
        }

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        data = self.http.get_json(
            f"{self._api()}/search",
            params={"q": query, "type_": "Posts", "limit": limit, "sort": "New"},
            headers=self._headers(),
        )
        out = []
        for pv in (data.get("posts") or [])[:limit]:
            p = pv.get("post") or {}
            creator = (pv.get("creator") or {}).get("name", "")
            out.append({
                "id": str(p.get("id", "")),
                "author": creator,
                "text": (p.get("name") or "")[:300],
                "url": p.get("ap_id") or p.get("url") or "",
            })
        return out

    def like(self, item: Dict[str, Any]) -> bool:
        resp = self.http.session.post(
            f"{self._api()}/post/like",
            json={"post_id": int(item["id"]), "score": 1},
            headers=self._headers(),
            timeout=self.http.timeout,
        )
        if resp.status_code >= 400:
            raise PlatformError(f"lemmy like: {resp.text[:200]}")
        return True

    def comment(self, item: Dict[str, Any], text: str) -> bool:
        resp = self.http.session.post(
            f"{self._api()}/comment",
            json={"post_id": int(item["id"]), "content": text},
            headers=self._headers(),
            timeout=self.http.timeout,
        )
        if resp.status_code >= 400:
            raise PlatformError(f"lemmy comment: {resp.text[:200]}")
        return True
