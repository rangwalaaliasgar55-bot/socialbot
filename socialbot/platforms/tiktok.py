"""TikTok — Content Posting API (Direct Post / draft).

Requires a TikTok developer app that has been approved for the Content Posting
API, plus a user access token with `video.publish` / `video.upload` scopes.

Flow (Direct Post):
  1. POST /v2/post/publish/video/init/  → upload_url + publish_id
  2. PUT binary chunks to upload_url
  3. Poll /v2/post/publish/status/fetch/ until PUBLISH_COMPLETE

App review typically takes 1–4 weeks. Until approved, the endpoints return
permission errors — the adapter surfaces those clearly.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import Post, PublishResult
from .base import Platform, PlatformError, download_media, register

API = "https://open.tiktokapis.com"


@register
class TikTok(Platform):
    name = "tiktok"
    display_name = "TikTok"
    color = "#010101"
    icon = "🎵"
    capabilities = {"post"}
    max_length = 2200
    site = "https://tiktok.com"
    docs_url = "https://developers.tiktok.com/doc/content-posting-api-get-started/"
    auth_fields = [
        {"key": "access_token", "label": "User access token", "required": True, "secret": True,
         "help": "OAuth token with video.publish / video.upload scopes"},
        {"key": "open_id", "label": "Open ID (optional)", "required": False, "secret": False,
         "help": "Returned by the OAuth flow; stored for reference"},
        {"key": "privacy_level", "label": "Privacy level", "required": False, "secret": False,
         "help": "PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS | SELF_ONLY (default PUBLIC_TO_EVERYONE)"},
        {"key": "disable_comment", "label": "Disable comments (true/false)", "required": False, "secret": False},
        {"key": "disable_duet", "label": "Disable duet (true/false)", "required": False, "secret": False},
        {"key": "disable_stitch", "label": "Disable stitch (true/false)", "required": False, "secret": False},
    ]

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.require('access_token')}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def verify(self) -> tuple:
        try:
            resp = self.http.session.get(
                f"{API}/v2/post/publish/creator_info/query/",
                headers=self._headers(),
                timeout=self.http.timeout,
            )
            body = resp.json() if resp.content else {}
            if resp.status_code >= 400 or body.get("error", {}).get("code") not in (None, "ok"):
                err = body.get("error", {}).get("message") or resp.text[:200]
                return False, f"tiktok auth: {err}"
            data = body.get("data") or {}
            name = data.get("creator_username") or data.get("nickname") or "creator"
            return True, f"@{name} ready for Content Posting API"
        except Exception as exc:
            return False, str(exc)

    def publish(self, post: Post) -> PublishResult:
        media = [m for m in post.media if m]
        if not media:
            raise PlatformError("TikTok requires a video file or URL in --media")

        source = media[0]
        caption = post.effective_text()[:2200]
        privacy = (self.setting("privacy_level") or "PUBLIC_TO_EVERYONE").upper()

        local_path: Optional[str] = None
        tmp: Optional[str] = None
        try:
            if source.startswith(("http://", "https://")):
                content, _ = download_media(source, self.http)
                fd, tmp = tempfile.mkstemp(suffix=".mp4")
                os.write(fd, content)
                os.close(fd)
                local_path = tmp
            else:
                path = Path(source)
                if not path.is_file():
                    raise PlatformError(f"video file not found: {source}")
                local_path = str(path)

            video_size = os.path.getsize(local_path)
            chunk_size = video_size
            total_chunks = 1

            init_body = {
                "post_info": {
                    "title": caption[:150] if caption else "SocialBot upload",
                    "description": caption,
                    "privacy_level": privacy,
                    "disable_comment": str(self.setting("disable_comment") or "false").lower() == "true",
                    "disable_duet": str(self.setting("disable_duet") or "false").lower() == "true",
                    "disable_stitch": str(self.setting("disable_stitch") or "false").lower() == "true",
                    "video_cover_timestamp_ms": 1000,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                },
            }

            init = self.http.session.post(
                f"{API}/v2/post/publish/video/init/",
                headers=self._headers(),
                json=init_body,
                timeout=30,
            )
            init_data = init.json() if init.content else {}
            if init.status_code >= 400 or init_data.get("error", {}).get("code") not in (None, "ok"):
                err = init_data.get("error", {}).get("message") or init.text[:300]
                raise PlatformError(
                    f"tiktok init failed: {err} "
                    "(ensure your app is approved for Content Posting API)"
                )
            data = init_data.get("data") or {}
            upload_url = data.get("upload_url")
            publish_id = data.get("publish_id")
            if not upload_url or not publish_id:
                raise PlatformError("tiktok init returned no upload_url / publish_id")

            with open(local_path, "rb") as fh:
                content_range = f"bytes 0-{video_size - 1}/{video_size}"
                put = self.http.session.put(
                    upload_url,
                    data=fh,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(video_size),
                        "Content-Range": content_range,
                    },
                    timeout=600,
                )
            if put.status_code not in (200, 201, 206):
                raise PlatformError(f"tiktok upload: HTTP {put.status_code} {put.text[:200]}")

            status = self._poll_status(publish_id)
            remote = status.get("publicaly_available_post_id") or status.get("publish_id") or publish_id
            if isinstance(remote, list):
                remote = remote[0] if remote else publish_id
            return PublishResult(
                platform=self.name, ok=True, remote_id=str(remote),
                url=None,
            )
        finally:
            if tmp and os.path.isfile(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def _poll_status(self, publish_id: str, attempts: int = 30, delay: float = 2.0) -> Dict[str, Any]:
        for _ in range(attempts):
            resp = self.http.session.post(
                f"{API}/v2/post/publish/status/fetch/",
                headers=self._headers(),
                json={"publish_id": publish_id},
                timeout=self.http.timeout,
            )
            body = resp.json() if resp.content else {}
            data = body.get("data") or {}
            status = data.get("status", "")
            if status in ("PUBLISH_COMPLETE", "FAILED"):
                if status == "FAILED":
                    raise PlatformError(f"tiktok publish failed: {data.get('fail_reason', data)}")
                return data
            time.sleep(delay)
        raise PlatformError("tiktok publish timed out waiting for PUBLISH_COMPLETE")
