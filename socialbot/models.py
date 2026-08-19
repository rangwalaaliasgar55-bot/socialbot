"""Core data models used across SocialBot (posts, results, bot rules)."""
from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

POST_STATUSES = ["draft", "scheduled", "publishing", "published", "partial", "failed", "cancelled"]


class PostStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PARTIAL = "partial"   # succeeded on some platforms only
    FAILED = "failed"
    CANCELLED = "cancelled"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}_{raw}" if prefix else raw


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string (tolerant of trailing 'Z') into an aware UTC datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class Post:
    """A social media post targeted at one or more platforms."""

    id: str = field(default_factory=lambda: new_id("post"))
    text: str = ""
    media: List[str] = field(default_factory=list)          # URLs or local file paths
    platforms: List[str] = field(default_factory=list)      # e.g. ["mastodon", "telegram"]
    status: str = PostStatus.DRAFT.value
    scheduled_at: Optional[str] = None                      # ISO-8601 UTC
    recurrence: Optional[Dict[str, Any]] = None             # {"type": "cron"|"interval", "value": ...}
    tag: Optional[str] = None                               # colored tag, Postiz style
    signature: Optional[str] = None                         # appended to text (per-account sig if unset)
    webhook_url: Optional[str] = None                       # called with payload after publish
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # platform -> result info
    error: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    created_at: str = field(default_factory=lambda: iso(utcnow()))
    published_at: Optional[str] = None

    # -- convenience -------------------------------------------------------
    def effective_text(self, platform: Optional[str] = None, account_signature: Optional[str] = None) -> str:
        sig = self.signature if self.signature is not None else account_signature
        text = self.text.rstrip()
        if sig:
            text = f"{text}\n\n{sig.strip()}"
        return text

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Post":
        d = dict(d)
        if isinstance(d.get("media"), str):
            d["media"] = [d["media"]]
        if isinstance(d.get("platforms"), str):
            d["platforms"] = [p for p in d["platforms"].split(",") if p]
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class PublishResult:
    """Outcome of publishing one post to one platform."""

    platform: str
    ok: bool
    remote_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    ts: str = field(default_factory=lambda: iso(utcnow()))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PublishResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class BotRule:
    """Automation rule: watch a trigger (keyword/hashtag search) and act (like/follow/comment)."""

    id: str = field(default_factory=lambda: new_id("rule"))
    name: str = "untitled rule"
    platform: str = ""                     # e.g. bluesky
    action: str = "like"                   # like | follow | comment | repost
    trigger_type: str = "keyword"          # keyword | hashtag
    trigger_value: str = ""                # the search query
    comment_template: str = ""             # used when action == comment
    limit_per_run: int = 5                 # max actions per run
    limit_per_hour: int = 20               # safety cap across runs
    dry_run: bool = True
    enabled: bool = True
    created_at: str = field(default_factory=lambda: iso(utcnow()))
    last_run: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None
    total_actions: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BotRule":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default
