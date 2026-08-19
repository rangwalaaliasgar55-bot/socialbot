"""LinkedIn — UGC post API (member posts)."""
from __future__ import annotations

from typing import Any, Dict

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

API = "https://api.linkedin.com"


@register
class LinkedIn(Platform):
    name = "linkedin"
    display_name = "LinkedIn"
    color = "#0A66C2"
    icon = "💼"
    capabilities = {"post", "delete"}
    max_length = 3000
    site = "https://linkedin.com"
    docs_url = "https://learn.microsoft.com/en-us/linkedin/marketing/"
    auth_fields = [
        {"key": "access_token", "label": "Access token", "required": True, "secret": True,
         "help": "w_member_social scope (Sign In with LinkedIn using OpenID Connect)"},
        {"key": "member_id", "label": "Member URN id", "required": True, "secret": False,
         "help": "e.g. 4t6Fv8rXkQ (from the 'sub' claim of your id token)"},
    ]

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.require('access_token')}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"}

    def publish(self, post: Post) -> PublishResult:
        member = str(self.require("member_id")).removeprefix("urn:li:person:")
        text = post.effective_text()[:3000]
        payload = {
            "author": f"urn:li:person:{member}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE"}},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}}
        try:
            data = self.http.post_json(f"{API}/v2/ugcPosts", json=payload, headers=self._headers())
        except Exception as exc:
            raise PlatformError(f"linkedin post failed: {exc}") from exc
        urn = data.get("id", "")
        return PublishResult(platform=self.name, ok=True, remote_id=urn,
                             url="https://www.linkedin.com/feed/updating/")

    def delete(self, remote_id: str) -> bool:
        urn = remote_id if remote_id.startswith("urn:li:share:") else f"urn:li:share:{remote_id}"
        self.http.request("DELETE", f"{API}/v2/ugcPosts/{urn}", headers=self._headers())
        return True
