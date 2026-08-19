"""Bluesky (AT Protocol) — post, media, delete, metrics, like/follow/comment, search."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..models import Post, PublishResult
from .base import Platform, PlatformError, download_media, register

PUBLIC_API = "https://bsky.social/xrpc"


@register
class Bluesky(Platform):
    name = "bluesky"
    display_name = "Bluesky"
    color = "#0A7AFF"
    icon = "🦋"
    capabilities = {"post", "delete", "metrics", "like", "follow", "comment", "repost", "search"}
    max_length = 300
    site = "https://bsky.app"
    docs_url = "https://atproto.com/"
    auth_fields = [
        {"key": "identifier", "label": "Handle", "required": True, "secret": False,
         "help": "e.g. you.bsky.social"},
        {"key": "password", "label": "App password", "required": True, "secret": True,
         "help": "Settings → App passwords"},
        {"key": "pds", "label": "PDS URL (optional)", "required": False, "secret": False,
         "help": "default https://bsky.social"},
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------- session
    def _api(self) -> str:
        pds = str(self.setting("pds") or PUBLIC_API).rstrip("/")
        return f"{pds}/xrpc"

    def _auth(self) -> Dict[str, str]:
        if self._session:
            return {"Authorization": f"Bearer {self._session['accessJwt']}"}
        data = self.http.post_json(
            f"{self._api()}/com.atproto.server.createSession",
            json={"identifier": self.require("identifier"), "password": self.require("password")})
        if not isinstance(data, dict) or "accessJwt" not in data:
            raise PlatformError("bluesky login failed")
        self._session = data
        return {"Authorization": f"Bearer {self._session['accessJwt']}"}

    def verify(self) -> tuple:
        try:
            auth = self._auth()
            return True, f"logged in as {self._session.get('handle', '?')}" if self._session else (True, "ok")
        except Exception as exc:
            return False, str(exc)

    # -------------------------------------------------------------- facets
    @staticmethod
    def _facets(text: str) -> List[Dict[str, Any]]:
        facets: List[Dict[str, Any]] = []

        def add(start: int, end: int, kind: str, value: Dict[str, Any]) -> None:
            facets.append({
                "index": {"byteStart": len(text[:start].encode("utf-8")),
                          "byteEnd": len(text[:end].encode("utf-8"))},
                "features": [{"$type": f"app.bsky.richtext.facet.{kind}", **value}]})

        for m in re.finditer(r"(?:^|\s)(#[\w]+)", text):
            s, e = m.span(1)
            add(s, e, "tag", {"tag": m.group(1)[1:]})
        for m in re.finditer(r"https?://\S+", text):
            add(*m.span(), "link", {"uri": m.group(0)})
        return facets

    def _upload_blob(self, source: str) -> Dict[str, Any]:
        content, mime = download_media(source, self.http)
        resp = self.http.session.post(
            f"{self._api()}/com.atproto.repo.uploadBlob", data=content,
            headers={**self._auth(), "Content-Type": mime}, timeout=self.http.timeout)
        if resp.status_code >= 400:
            raise PlatformError(f"bluesky media upload: {resp.text[:200]}")
        return resp.json()["blob"]

    # ----------------------------------------------------------- publishing
    def publish(self, post: Post) -> PublishResult:
        text = post.effective_text()
        if len(text) > self.max_length:
            text = text[: self.max_length - 1] + "…"
        record: Dict[str, Any] = {
            "$type": "app.bsky.feed.post", "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        facets = self._facets(text)
        if facets:
            record["facets"] = facets
        if post.media:
            images = [{"alt": "", "image": self._upload_blob(m)} for m in post.media[:4]]
            record["embed"] = {"$type": "app.bsky.embed.images", "images": images}
        created = self.http.post_json(
            f"{self._api()}/com.atproto.repo.createRecord",
            json={"repo": self._session["did"] if self._session else self.setting("identifier"),
                  "collection": "app.bsky.feed.post", "record": record},
            headers=self._auth())
        uri = created.get("uri", "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        handle = (self._session or {}).get("handle", self.setting("identifier", "user"))
        return PublishResult(platform=self.name, ok=True, remote_id=uri,
                             url=f"https://bsky.app/profile/{handle}/post/{rkey}")

    def delete(self, remote_id: str) -> bool:
        uri = remote_id if remote_id.startswith("at://") else remote_id
        rkey = uri.rsplit("/", 1)[-1]
        self.http.post_json(
            f"{self._api()}/com.atproto.repo.deleteRecord",
            json={"repo": self._session["did"] if self._session else self.setting("identifier"),
                  "collection": "app.bsky.feed.post", "rkey": rkey},
            headers=self._auth())
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        data = self.http.get_json(f"{self._api()}/app.bsky.feed.getPosts",
                                  params={"uris": remote_id}, headers=self._auth())
        posts = data.get("posts", [])
        if not posts:
            return {}
        p = posts[0]
        return {"likes": p.get("likeCount", 0), "shares": p.get("repostCount", 0),
                "comments": p.get("replyCount", 0)}

    # -------------------------------------------------------- bot operations
    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        data = self.http.get_json(
            f"{self._api()}/app.bsky.feed.searchPosts",
            params={"q": query, "limit": limit}, headers=self._auth())
        out = []
        for p in data.get("posts", [])[:limit]:
            author = p.get("author", {})
            out.append({"id": p.get("uri"), "cid": p.get("cid", ""),
                        "author": author.get("handle", ""), "author_id": author.get("did", ""),
                        "text": p.get("record", {}).get("text", "")[:300],
                        "url": f"https://bsky.app/profile/{author.get('handle', '')}"
                               f"/post/{p.get('uri', '').rsplit('/', 1)[-1]}"})
        return out

    def _create_record(self, collection: str, record: Dict[str, Any]) -> Dict[str, Any]:
        return self.http.post_json(
            f"{self._api()}/com.atproto.repo.createRecord",
            json={"repo": self._session["did"] if self._session else self.setting("identifier"),
                  "collection": collection, "record": record},
            headers=self._auth())

    def like(self, item: Dict[str, Any]) -> bool:
        if not item.get("cid"):
            raise PlatformError("bluesky like requires post cid")
        self._create_record("app.bsky.feed.like", {
            "$type": "app.bsky.feed.like", "subject": {"uri": item["id"], "cid": item["cid"]},
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
        return True

    def repost(self, item: Dict[str, Any]) -> bool:
        if not item.get("cid"):
            raise PlatformError("bluesky repost requires post cid")
        self._create_record("app.bsky.feed.repost", {
            "$type": "app.bsky.feed.repost", "subject": {"uri": item["id"], "cid": item["cid"]},
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
        return True

    def follow(self, item: Dict[str, Any]) -> bool:
        if not item.get("author_id"):
            raise PlatformError("no author did available for follow")
        self._create_record("app.bsky.graph.follow", {
            "$type": "app.bsky.graph.follow", "subject": item["author_id"],
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
        return True

    def comment(self, item: Dict[str, Any], text: str) -> bool:
        if not item.get("cid"):
            raise PlatformError("bluesky comment requires post cid")
        record = {
            "$type": "app.bsky.feed.post", "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reply": {"root": {"uri": item["id"], "cid": item["cid"]},
                      "parent": {"uri": item["id"], "cid": item["cid"]}}}
        self._create_record("app.bsky.feed.post", record)
        return True
