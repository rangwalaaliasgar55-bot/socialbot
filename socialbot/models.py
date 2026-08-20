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
    variants: Dict[str, str] = field(default_factory=dict)  # per-platform text overrides
    thread: bool = False                                    # split long text into a thread/carousel
    thread_parts: List[str] = field(default_factory=list)   # precomputed parts (after auto-split)
    best_time: bool = False                                 # schedule at the optimal engagement window
    origin: Optional[str] = None                            # feed:name | trend:platform:topic | competitor:id
    review_status: Optional[str] = None                     # pending | approved | rejected (agent drafts)
    reviewed_at: Optional[str] = None                       # when the review decision was made

    # -- convenience -------------------------------------------------------
    def effective_text(self, platform: Optional[str] = None, account_signature: Optional[str] = None) -> str:
        sig = self.signature if self.signature is not None else account_signature
        text = (self.variants.get(platform) if platform and self.variants.get(platform) else self.text).rstrip()
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
    interests: str = ""                    # comma-separated topics; empty = any (smart engagement filter)
    min_sentiment: float = 0.0             # only engage items scoring at least this (-1..1)
    whitelist_only: bool = False           # only engage whitelisted accounts
    skip_blacklisted: bool = True          # never engage blacklisted accounts
    max_per_day: int = 200                 # daily safety cap across all runs

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BotRule":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class MentionRule:
    """Mention & hashtag monitor: watch a query, meaningfully engage new posts."""

    id: str = field(default_factory=lambda: new_id("mon"))
    name: str = "untitled monitor"
    platform: str = ""                     # e.g. bluesky
    query: str = ""                        # hashtag / keyword / @mention watched
    action: str = "like"                   # like | follow | comment | repost | quote
    comment_template: str = ""             # when action == comment / quote
    limit_per_run: int = 5
    limit_per_hour: int = 20
    dry_run: bool = True
    dedupe: bool = True                    # only act on posts not seen before
    min_sentiment: float = 0.0
    whitelist_only: bool = False
    skip_blacklisted: bool = True
    enabled: bool = True
    created_at: str = field(default_factory=lambda: iso(utcnow()))
    last_run: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MentionRule":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class InboxRule:
    """Inbox responder: auto-answer DMs/mentions that match known intents."""

    id: str = field(default_factory=lambda: new_id("inb"))
    name: str = "untitled responder"
    platform: str = ""                     # e.g. mock
    intents: List[str] = field(default_factory=lambda: ["pricing", "demo", "thanks", "complaint"])
    auto_reply: bool = True
    reply_template: str = ""               # override per-intent replies
    escalate_webhook: Optional[str] = None # notified on complaint / unknown intents
    max_per_run: int = 10
    enabled: bool = True
    created_at: str = field(default_factory=lambda: iso(utcnow()))
    last_run: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InboxRule":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class CompetitorRule:
    """Competitor watch: track competitor accounts and surface content gaps."""

    id: str = field(default_factory=lambda: new_id("cmp"))
    name: str = "untitled watch"
    platform: str = ""                     # e.g. mastodon
    competitors: List[str] = field(default_factory=list)  # usernames to watch
    interests: str = ""                    # comma-separated topics that matter to you
    create_drafts: bool = True             # auto-draft posts for uncovered topics
    limit_per_competitor: int = 10
    enabled: bool = True
    created_at: str = field(default_factory=lambda: iso(utcnow()))
    last_run: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CompetitorRule":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class FeedSource:
    """Content source: an RSS feed or a curated list of items."""

    id: str = field(default_factory=lambda: new_id("feed"))
    name: str = "untitled source"
    kind: str = "rss"                      # rss | curated
    url: str = ""                          # RSS URL (kind == rss)
    items: List[Dict[str, Any]] = field(default_factory=list)  # curated items [{title, link, summary}]
    interval_min: int = 60                 # how often to pull
    n_drafts: int = 3                      # drafts to generate per pull
    auto_draft: bool = True                # save generated posts as drafts
    target_platforms: List[str] = field(default_factory=list)  # default platforms for drafts
    enabled: bool = True
    created_at: str = field(default_factory=lambda: iso(utcnow()))
    last_run: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FeedSource":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class SafetyRule:
    """Blacklist / whitelist entry: never (or always) engage this account."""

    id: str = field(default_factory=lambda: new_id("sft"))
    list_type: str = "blacklist"           # blacklist | whitelist
    platform: str = ""                     # '' = all platforms
    username: str = ""
    note: str = ""
    created_at: str = field(default_factory=lambda: iso(utcnow()))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SafetyRule":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class UserProfile:
    """Learned profile of a user we engaged with (interests, activity, sentiment)."""

    id: str = field(default_factory=lambda: new_id("prof"))
    platform: str = ""
    username: str = ""
    data: Dict[str, Any] = field(default_factory=dict)  # interests, activity_hours, sentiment…
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    updated_at: str = field(default_factory=lambda: iso(utcnow()))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UserProfile":
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
