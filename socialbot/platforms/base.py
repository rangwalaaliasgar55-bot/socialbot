"""Platform base class + registry.

Every social network is a subclass of :class:`Platform` registered by name.
The registry lets the CLI, scheduler, bot engine and API treat all networks
uniformly (same way Postiz abstracts providers).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Type

import requests

from ..http import HttpClient
from ..models import Post, PublishResult

_REGISTRY: Dict[str, Type["Platform"]] = {}


class PlatformError(Exception):
    """Raised by platform implementations on a recoverable failure."""


class Platform(ABC):
    """A social network integration."""

    name: str = "base"                 # registry key, lowercase
    display_name: str = "Base"
    color: str = "#7c8ba1"             # dashboard accent
    icon: str = "●"
    auth_fields: List[Dict[str, Any]] = []
    capabilities: Set[str] = set()     # post, delete, metrics, like, follow, comment, repost, search
    max_length: Optional[int] = None   # text limit; None = unlimited
    site: str = ""
    docs_url: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None, http: Optional[HttpClient] = None):
        self.config: Dict[str, Any] = dict(config or {})
        self.http = http or HttpClient()

    # ------------------------------------------------------------- config
    def env_key(self, suffix: str) -> str:
        return f"{self.name.upper()}_{suffix}"

    def setting(self, key: str, default: Any = None) -> Any:
        """Look up a setting in account config, then SOCIALBOT env, then plain env."""
        env_val = os.environ.get(self.env_key(key.upper()))
        return self.config.get(key, env_val if env_val is not None else default)

    def require(self, key: str) -> Any:
        val = self.setting(key)
        if not val:
            raise PlatformError(
                f"[{self.display_name}] missing required setting '{key}' — add it via "
                f"`socialbot accounts add {self.name}` or set {self.env_key(key.upper())}")
        return val

    def is_configured(self) -> bool:
        try:
            for field in self.auth_fields:
                if field.get("required", True) and not self.setting(field["key"]):
                    return False
            return True
        except Exception:
            return False

    def missing_fields(self) -> List[str]:
        return [f["key"] for f in self.auth_fields
                if f.get("required", True) and not self.setting(f["key"])]

    def verify(self) -> tuple:  # (ok, message)
        """Light credential check. Default: configuration present."""
        missing = self.missing_fields()
        if missing:
            return False, "missing: " + ", ".join(missing)
        return True, "configured"

    # ---------------------------------------------------------- publishing
    @abstractmethod
    def publish(self, post: Post) -> PublishResult:
        """Publish *post* to this platform. Return a PublishResult.

        Implementations should raise PlatformError for expected/retryable
        failures; unexpected exceptions are caught by the publisher.
        """

    def delete(self, remote_id: str) -> bool:  # pragma: no cover - optional
        raise PlatformError(f"{self.display_name} does not support delete")

    def get_metrics(self, remote_id: str) -> Dict[str, Any]:  # pragma: no cover - optional
        raise PlatformError(f"{self.display_name} does not support metrics")

    # ------------------------------------------------------- bot operations
    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        raise PlatformError(f"{self.display_name} does not support search")

    def like(self, item: Dict[str, Any]) -> bool:
        raise PlatformError(f"{self.display_name} does not support like")

    def follow(self, item: Dict[str, Any]) -> bool:
        raise PlatformError(f"{self.display_name} does not support follow")

    def comment(self, item: Dict[str, Any], text: str) -> bool:
        raise PlatformError(f"{self.display_name} does not support comment")

    def repost(self, item: Dict[str, Any]) -> bool:
        raise PlatformError(f"{self.display_name} does not support repost")


# ------------------------------------------------------------------ registry
def register(cls: Type[Platform]) -> Type[Platform]:
    _REGISTRY[cls.name] = cls
    return cls


def get_platform_class(name: str) -> Type[Platform]:
    key = (name or "").strip().lower()
    if key not in _REGISTRY:
        raise PlatformError(f"unknown platform '{name}'. available: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[key]


def platform_names() -> List[str]:
    return sorted(_REGISTRY)


def platform_meta() -> List[Dict[str, Any]]:
    out = []
    for name in sorted(_REGISTRY, key=lambda n: _REGISTRY[n].display_name):
        cls = _REGISTRY[name]
        out.append({
            "name": cls.name,
            "display_name": cls.display_name,
            "color": cls.color,
            "icon": cls.icon,
            "capabilities": sorted(cls.capabilities),
            "auth_fields": cls.auth_fields,
            "max_length": cls.max_length,
            "site": cls.site,
            "docs_url": cls.docs_url,
        })
    return out


def create_platform(name: str, config: Optional[Dict[str, Any]] = None,
                    http: Optional[HttpClient] = None) -> Platform:
    return get_platform_class(name)(config or {}, http)


# ------------------------------------------------------------------- helpers
def download_media(source: str, http: Optional[HttpClient] = None) -> tuple:
    """Fetch media from a URL or local path -> (bytes, mime_type)."""
    if source.startswith(("http://", "https://")):
        client = http or HttpClient(timeout=60)
        resp = client.session.get(source, timeout=client.timeout)
        if resp.status_code >= 400:
            raise PlatformError(f"could not download media {source}: HTTP {resp.status_code}")
        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        return resp.content, mime
    path = Path(source)
    if not path.is_file():
        raise PlatformError(f"media file not found: {source}")
    mime = "image/png" if path.suffix.lower() == ".png" else \
           "image/webp" if path.suffix.lower() == ".webp" else \
           "video/mp4" if path.suffix.lower() == ".mp4" else "image/jpeg"
    return path.read_bytes(), mime


def guess_description(post: Post) -> str:
    return post.text.strip().split("\n")[0][:100] or "socialbot post"
