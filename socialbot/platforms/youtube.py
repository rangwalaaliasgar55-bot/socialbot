"""YouTube — upload videos via the official Data API v3 (OAuth access token).

Requires a Google Cloud project with YouTube Data API v3 enabled and an OAuth
access token that has the `youtube.upload` scope. Video files (local path or
HTTP URL) are uploaded with resumable upload; text-only posts are not supported
(YouTube is video-centric).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ..models import Post, PublishResult
from .base import Platform, PlatformError, download_media, register

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3"


@register
class YouTube(Platform):
    name = "youtube"
    display_name = "YouTube"
    color = "#FF0000"
    icon = "▶️"
    capabilities = {"post", "delete", "metrics"}
    max_length = 5000          # description limit
    site = "https://youtube.com"
    docs_url = "https://developers.google.com/youtube/v3/docs/videos/insert"
    auth_fields = [
        {"key": "access_token", "label": "OAuth access token", "required": True, "secret": True,
         "help": "Google OAuth token with youtube.upload scope (or full youtube scope)"},
        {"key": "refresh_token", "label": "Refresh token (optional)", "required": False, "secret": True,
         "help": "Used to refresh the access token when it expires"},
        {"key": "client_id", "label": "OAuth client ID (for refresh)", "required": False, "secret": True},
        {"key": "client_secret", "label": "OAuth client secret (for refresh)", "required": False, "secret": True},
        {"key": "privacy", "label": "Default privacy (public|unlisted|private)", "required": False,
         "secret": False, "help": "Defaults to unlisted"},
        {"key": "category_id", "label": "Category ID", "required": False, "secret": False,
         "help": "e.g. 22 = People & Blogs (default)"},
    ]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}"}

    def _maybe_refresh(self) -> None:
        """Best-effort token refresh if refresh credentials are present."""
        refresh = self.setting("refresh_token")
        cid = self.setting("client_id")
        secret = self.setting("client_secret")
        if not (refresh and cid and secret):
            return
        try:
            resp = self.http.session.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": cid,
                    "client_secret": secret,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
                timeout=self.http.timeout,
            )
            if resp.ok:
                data = resp.json()
                if data.get("access_token"):
                    self.config["access_token"] = data["access_token"]
        except Exception:
            pass  # keep using the existing token

    def verify(self) -> tuple:
        self._maybe_refresh()
        try:
            data = self.http.get_json(
                f"{API_URL}/channels",
                params={"part": "snippet", "mine": "true"},
                headers=self._headers(),
            )
            items = data.get("items") or []
            if not items:
                return False, "token valid but no channel found (enable YouTube Data API)"
            title = items[0].get("snippet", {}).get("title", "?")
            return True, f"channel '{title}' ready"
        except Exception as exc:
            return False, str(exc)

    def publish(self, post: Post) -> PublishResult:
        self._maybe_refresh()
        media = [m for m in post.media if m]
        if not media:
            raise PlatformError(
                "YouTube requires a video file or URL in --media "
                "(text-only community posts are not supported via this API)"
            )

        source = media[0]
        title = (post.effective_text().split("\n")[0] or "SocialBot upload")[:100]
        description = post.effective_text()[:5000]
        privacy = (self.setting("privacy") or "unlisted").lower()
        if privacy not in ("public", "unlisted", "private"):
            privacy = "unlisted"
        category = str(self.setting("category_id") or "22")

        local_path: Optional[str] = None
        tmp: Optional[str] = None
        try:
            if source.startswith(("http://", "https://")):
                content, mime = download_media(source, self.http)
                fd, tmp = tempfile.mkstemp(suffix=".mp4")
                os.write(fd, content)
                os.close(fd)
                local_path = tmp
            else:
                path = Path(source)
                if not path.is_file():
                    raise PlatformError(f"video file not found: {source}")
                local_path = str(path)

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "categoryId": category,
                },
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }

            init_headers = {
                **self._headers(),
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/*",
                "X-Upload-Content-Length": str(os.path.getsize(local_path)),
            }
            init = self.http.session.post(
                f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
                headers=init_headers,
                data=json.dumps(body),
                timeout=60,
            )
            if init.status_code not in (200, 201):
                raise PlatformError(f"youtube upload init: HTTP {init.status_code} {init.text[:300]}")
            upload_url = init.headers.get("Location")
            if not upload_url:
                raise PlatformError("youtube upload init returned no Location header")

            with open(local_path, "rb") as fh:
                put = self.http.session.put(
                    upload_url,
                    data=fh,
                    headers={"Content-Type": "video/*"},
                    timeout=600,
                )
            if put.status_code not in (200, 201):
                raise PlatformError(f"youtube upload: HTTP {put.status_code} {put.text[:300]}")
            data = put.json()
            vid = data.get("id", "")
            return PublishResult(
                platform=self.name, ok=True, remote_id=vid,
                url=f"https://www.youtube.com/watch?v={vid}" if vid else None,
            )
        finally:
            if tmp and os.path.isfile(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def delete(self, remote_id: str) -> bool:
        self._maybe_refresh()
        resp = self.http.session.delete(
            f"{API_URL}/videos",
            params={"id": remote_id},
            headers=self._headers(),
            timeout=self.http.timeout,
        )
        if resp.status_code >= 400:
            raise PlatformError(f"youtube delete: HTTP {resp.status_code} {resp.text[:200]}")
        return True

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:
        self._maybe_refresh()
        data = self.http.get_json(
            f"{API_URL}/videos",
            params={"part": "statistics", "id": remote_id},
            headers=self._headers(),
        )
        items = data.get("items") or []
        if not items:
            return {}
        s = items[0].get("statistics", {})
        return {
            "views": int(s.get("viewCount", 0) or 0),
            "likes": int(s.get("likeCount", 0) or 0),
            "comments": int(s.get("commentCount", 0) or 0),
        }
