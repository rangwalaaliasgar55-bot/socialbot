"""Reddit — OAuth2 script app: submit posts, comment, upvote, search, metrics."""
from __future__ import annotations

from typing import Any, Dict, List

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
USER_AGENT = "socialbot/1.0 (github.com/rangwalaaliasgar55-bot/socialbot)"


@register
class Reddit(Platform):
    name = "reddit"
    display_name = "Reddit"
    color = "#FF4500"
    icon = "👽"
    capabilities = {"post", "delete", "metrics", "comment", "like", "search"}
    max_length = 40000
    site = "https://reddit.com"
    docs_url = "https://www.reddit.com/dev/api/"
    auth_fields = [
        {"key": "client_id", "label": "Client ID", "required": True, "secret": True,
         "help": "reddit.com/prefs/apps → script app"},
        {"key": "client_secret", "label": "Client secret", "required": True, "secret": True},
        {"key": "username", "label": "Reddit username", "required": True, "secret": False},
        {"key": "password", "label": "Password", "required": True, "secret": True},
        {"key": "subreddit", "label": "Default subreddit (no r/)", "required": False, "secret": False},
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._token: str = ""

    def _headers(self) -> Dict[str, str]:
        if not self._token:
            self._token = self._token_request()
        return {"Authorization": f"bearer {self._token}", "User-Agent": USER_AGENT}

    def _token_request(self) -> str:
        auth = (self.require("client_id"), self.require("client_secret"))
        resp = self.http.session.post(
            TOKEN_URL, auth=auth,
            data={"grant_type": "password", "username": self.require("username"),
                  "password": self.require("password")},
            headers={"User-Agent": USER_AGENT}, timeout=self.http.timeout)
        if resp.status_code >= 400:
            raise PlatformError(f"reddit auth failed: {resp.text[:200]}")
        token = resp.json().get("access_token")
        if not token:
            raise PlatformError("reddit auth returned no token")
        return token

    def verify(self) -> tuple:
        try:
            headers = self._headers()
            return True, f"authenticated as u/{self.setting('username')}"
        except Exception as exc:
            return False, str(exc)

    # ----------------------------------------------------------- publishing
    def publish(self, post: Post) -> PublishResult:
        subreddit = str(self.setting("subreddit") or "").strip() or None
        if not subreddit:
            raise PlatformError("no subreddit configured for this post (account setting 'subreddit')")
        subreddit = subreddit.removeprefix("r/")

        lines = [ln.strip() for ln in post.effective_text().split("\n") if ln.strip()]
        title = (lines[0] if lines else "post")[:300]
        body = "\n".join(lines[1:]) or ""

        data: Dict[str, Any] = {"sr": subreddit, "title": title, "api_type": "json"}
        link = next((m for m in post.media if m.startswith("http")), None)
        if link and not body:
            data.update({"kind": "link", "url": link})
        else:
            data.update({"kind": "self", "text": body or title})

        resp = self.http.session.post(f"{API}/api/submit", data=data,
                                      headers=self._headers(), timeout=self.http.timeout)
        return self._parse_submit(resp)

    def _parse_submit(self, resp) -> PublishResult:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise PlatformError(f"reddit submit: HTTP {resp.status_code}") from exc
        if resp.status_code >= 400 or payload.get("json", {}).get("errors"):
            errors = payload.get("json", {}).get("errors") or resp.text[:200]
            raise PlatformError(f"reddit submit failed: {errors}")
        rd = payload["json"]["data"]
        return PublishResult(platform=self.name, ok=True, remote_id=rd.get("id", ""),
                             url=rd.get("url", ""))

    def delete(self, remote_id: str) -> bool:
        full = remote_id if remote_id.startswith("t3_") else f"t3_{remote_id}"
        self.http.session.post(f"{API}/api/del", data={"id": full},
                               headers=self._headers(), timeout=self.http.timeout)
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        full = remote_id if remote_id.startswith("t3_") else f"t3_{remote_id}"
        data = self.http.get_json(f"{API}/api/info", params={"id": full}, headers=self._headers())
        children = data.get("data", {}).get("children", [])
        if not children:
            return {}
        d = children[0]["data"]
        return {"likes": d.get("score", 0), "comments": d.get("num_comments", 0),
                "upvote_ratio": d.get("upvote_ratio")}

    # -------------------------------------------------------- bot operations
    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        data = self.http.get_json(f"{API}/search", params={"q": query, "limit": limit, "sort": "new",
                                                           "type": "link", "raw_json": 1},
                                  headers=self._headers())
        out = []
        for child in data.get("data", {}).get("children", [])[:limit]:
            d = child["data"]
            out.append({"id": f"t3_{d.get('id')}", "author": d.get("author", ""),
                        "text": d.get("title", "")[:300], "url": d.get("url", ""),
                        "permalink": f"https://reddit.com{d.get('permalink', '')}"})
        return out

    def like(self, item: Dict[str, Any]) -> bool:
        self.http.session.post(f"{API}/api/vote", data={"id": item["id"], "dir": 1},
                               headers=self._headers(), timeout=self.http.timeout)
        return True

    def comment(self, item: Dict[str, Any], text: str) -> bool:
        resp = self.http.session.post(f"{API}/api/comment",
                                      data={"thing_id": item["id"], "text": text, "api_type": "json"},
                                      headers=self._headers(), timeout=self.http.timeout)
        if resp.status_code >= 400:
            raise PlatformError(f"reddit comment failed: {resp.text[:200]}")
        return True
