"""SQLite persistence for posts, accounts, bot rules, metrics and events.

Zero-config: the database is created on first use at ``socialbot.db`` (or the
path given by ``SOCIALBOT_DB`` / the app config).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from .models import (BotRule, CompetitorRule, FeedSource, InboxRule, MentionRule,
                     Post, SafetyRule, UserProfile, dumps, loads, new_id, utcnow, iso)

DEFAULT_DB = os.environ.get("SOCIALBOT_DB") or os.path.join(os.getcwd(), "socialbot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL DEFAULT '',
    media_json TEXT NOT NULL DEFAULT '[]',
    platforms_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TEXT,
    recurrence_json TEXT,
    tag TEXT,
    signature TEXT,
    webhook_url TEXT,
    results_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL,
    published_at TEXT,
    variants_json TEXT NOT NULL DEFAULT '{}',
    thread INTEGER NOT NULL DEFAULT 0,
    thread_parts_json TEXT NOT NULL DEFAULT '[]',
    best_time INTEGER NOT NULL DEFAULT 0,
    origin TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts(scheduled_at);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_rules (
    id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    remote_id TEXT,
    captured_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_metrics_post ON metrics(post_id);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS safety_rules (
    id TEXT PRIMARY KEY,
    list_type TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_safety_username ON safety_rules(username);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    username TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    first_seen TEXT,
    last_seen TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, username)
);

CREATE TABLE IF NOT EXISTS feed_sources (
    id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitors (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inbox_rules (
    id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trends (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    topic TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    month TEXT NOT NULL UNIQUE,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    platform TEXT NOT NULL,
    remote_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    UNIQUE(kind, remote_id)
);

CREATE TABLE IF NOT EXISTS rate_buckets (
    key TEXT PRIMARY KEY,
    tokens REAL NOT NULL,
    last_refill TEXT NOT NULL
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns added after v1.1.0 to existing databases (best effort)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    additions = {
        "variants_json": "TEXT NOT NULL DEFAULT '{}'",
        "thread": "INTEGER NOT NULL DEFAULT 0",
        "thread_parts_json": "TEXT NOT NULL DEFAULT '[]'",
        "best_time": "INTEGER NOT NULL DEFAULT 0",
        "origin": "TEXT",
    }
    for column, definition in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {column} {definition}")


class Store:
    """Thread-safe SQLite store (SQLite connections are per-thread)."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or DEFAULT_DB
        self._local = threading.local()
        self._write_lock = threading.RLock()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            _migrate(conn)

    # ------------------------------------------------------------------ util
    @contextmanager
    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        yield conn
        with self._write_lock:
            conn.commit()

    @staticmethod
    def _row_to_post(row: sqlite3.Row) -> Post:
        return Post.from_dict({
            "id": row["id"],
            "text": row["text"],
            "media": loads(row["media_json"], []),
            "platforms": loads(row["platforms_json"], []),
            "status": row["status"],
            "scheduled_at": row["scheduled_at"],
            "recurrence": loads(row["recurrence_json"]),
            "tag": row["tag"],
            "signature": row["signature"],
            "webhook_url": row["webhook_url"],
            "results": loads(row["results_json"], {}),
            "error": row["error"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "created_at": row["created_at"],
            "published_at": row["published_at"],
            "variants": loads(row["variants_json"], {}),
            "thread": bool(row["thread"]),
            "thread_parts": loads(row["thread_parts_json"], []),
            "best_time": bool(row["best_time"]),
            "origin": row["origin"],
        })

    # ----------------------------------------------------------------- posts
    def save_post(self, post: Post) -> Post:
        with self._conn() as c:
            c.execute(
                """INSERT INTO posts (id, text, media_json, platforms_json, status, scheduled_at,
                     recurrence_json, tag, signature, webhook_url, results_json, error, attempts,
                     max_attempts, created_at, published_at, variants_json, thread,
                     thread_parts_json, best_time, origin)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     text=excluded.text, media_json=excluded.media_json,
                     platforms_json=excluded.platforms_json, status=excluded.status,
                     scheduled_at=excluded.scheduled_at, recurrence_json=excluded.recurrence_json,
                     tag=excluded.tag, signature=excluded.signature, webhook_url=excluded.webhook_url,
                     results_json=excluded.results_json, error=excluded.error,
                     attempts=excluded.attempts, max_attempts=excluded.max_attempts,
                     published_at=excluded.published_at, variants_json=excluded.variants_json,
                     thread=excluded.thread, thread_parts_json=excluded.thread_parts_json,
                     best_time=excluded.best_time, origin=excluded.origin""",
                (post.id, post.text, dumps(post.media), dumps(post.platforms), post.status,
                 post.scheduled_at, dumps(post.recurrence), post.tag, post.signature,
                 post.webhook_url, dumps(post.results), post.error, post.attempts,
                 post.max_attempts, post.created_at, post.published_at, dumps(post.variants),
                 1 if post.thread else 0, dumps(post.thread_parts),
                 1 if post.best_time else 0, post.origin))
        return post

    def get_post(self, post_id: str) -> Optional[Post]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        return self._row_to_post(row) if row else None

    def list_posts(self, status: Optional[str] = None, limit: int = 500) -> List[Post]:
        q = "SELECT * FROM posts"
        args: list = []
        if status:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY COALESCE(scheduled_at, created_at) DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [self._row_to_post(r) for r in rows]

    def delete_post(self, post_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM posts WHERE id=?", (post_id,))
        return cur.rowcount > 0

    def due_posts(self, now_iso: str) -> List[Post]:
        """Posts scheduled at or before *now_iso* that are still pending."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM posts WHERE status IN ('scheduled') AND scheduled_at IS NOT NULL "
                "AND scheduled_at <= ? ORDER BY scheduled_at ASC LIMIT 50", (now_iso,)).fetchall()
        return [self._row_to_post(r) for r in rows]

    # -------------------------------------------------------------- accounts
    def save_account(self, platform: str, config: Dict[str, Any], label: str = "",
                     enabled: bool = True, account_id: Optional[str] = None) -> Dict[str, Any]:
        acc_id = account_id or new_id("acc")
        with self._conn() as c:
            existing = c.execute("SELECT id FROM accounts WHERE platform=?", (platform,)).fetchone()
            if existing:
                acc_id = existing["id"]
            c.execute(
                """INSERT INTO accounts (id, platform, label, config_json, enabled, created_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(platform) DO UPDATE SET
                     label=excluded.label, config_json=excluded.config_json,
                     enabled=excluded.enabled""",
                (acc_id, platform, label, dumps(config), 1 if enabled else 0, iso(utcnow())))
        return self.get_account(platform)  # type: ignore[return-value]

    def get_account(self, platform: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM accounts WHERE platform=?", (platform,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"], "platform": row["platform"], "label": row["label"],
            "config": loads(row["config_json"], {}), "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
        }

    def list_accounts(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM accounts ORDER BY platform").fetchall()
        out = []
        for row in rows:
            out.append({
                "id": row["id"], "platform": row["platform"], "label": row["label"],
                "config": loads(row["config_json"], {}), "enabled": bool(row["enabled"]),
                "created_at": row["created_at"]})
        return out

    def delete_account(self, platform: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM accounts WHERE platform=?", (platform,))
        return cur.rowcount > 0

    # ------------------------------------------------------------- bot rules
    def save_rule(self, rule: BotRule) -> BotRule:
        with self._conn() as c:
            c.execute("INSERT INTO bot_rules (id, data_json) VALUES (?,?) "
                      "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                      (rule.id, dumps(rule.to_dict())))
        return rule

    def get_rule(self, rule_id: str) -> Optional[BotRule]:
        with self._conn() as c:
            row = c.execute("SELECT data_json FROM bot_rules WHERE id=?", (rule_id,)).fetchone()
        return BotRule.from_dict(loads(row["data_json"])) if row else None

    def list_rules(self, only_enabled: bool = False) -> List[BotRule]:
        with self._conn() as c:
            rows = c.execute("SELECT data_json FROM bot_rules ORDER BY id").fetchall()
        rules = [BotRule.from_dict(loads(r["data_json"])) for r in rows]
        if only_enabled:
            rules = [r for r in rules if r.enabled]
        return rules

    def delete_rule(self, rule_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM bot_rules WHERE id=?", (rule_id,))
        return cur.rowcount > 0

    # --------------------------------------------------------------- metrics
    def save_metrics(self, post_id: str, platform: str, remote_id: Optional[str],
                     metrics: Dict[str, Any], captured_at: Optional[str] = None) -> str:
        mid = new_id("m")
        with self._conn() as c:
            c.execute("INSERT INTO metrics (id, post_id, platform, remote_id, captured_at, metrics_json) "
                      "VALUES (?,?,?,?,?,?)",
                      (mid, post_id, platform, remote_id, captured_at or iso(utcnow()), dumps(metrics)))
        return mid

    def latest_metrics(self, post_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as c:
            if post_id:
                rows = c.execute("SELECT * FROM metrics WHERE post_id=? ORDER BY captured_at DESC",
                                 (post_id,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM metrics ORDER BY captured_at DESC LIMIT 2000").fetchall()
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for r in rows:
            key = (r["post_id"], r["platform"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"post_id": r["post_id"], "platform": r["platform"],
                        "remote_id": r["remote_id"], "captured_at": r["captured_at"],
                        "metrics": loads(r["metrics_json"], {})})
            if len(out) >= limit:
                break
        return out

    # ---------------------------------------------------------------- events
    def log_event(self, type_: str, message: str, data: Optional[Dict[str, Any]] = None) -> str:
        eid = new_id("evt")
        with self._conn() as c:
            c.execute("INSERT INTO events (id, ts, type, message, data_json) VALUES (?,?,?,?,?)",
                      (eid, iso(utcnow()), type_, message, dumps(data or {})))
        return eid

    def list_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "type": r["type"], "message": r["message"],
                 "data": loads(r["data_json"], {})} for r in rows]

    # ------------------------------------------------------ safety (black/white lists)
    def save_safety_rule(self, rule: SafetyRule) -> SafetyRule:
        with self._conn() as c:
            c.execute("INSERT INTO safety_rules (id, list_type, platform, username, note, created_at) "
                      "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                      "list_type=excluded.list_type, platform=excluded.platform, "
                      "username=excluded.username, note=excluded.note",
                      (rule.id, rule.list_type, rule.platform, rule.username, rule.note,
                       rule.created_at))
        return rule

    def list_safety_rules(self, list_type: Optional[str] = None) -> List[SafetyRule]:
        q = "SELECT * FROM safety_rules"
        args: list = []
        if list_type:
            q += " WHERE list_type=?"
            args.append(list_type)
        q += " ORDER BY created_at DESC"
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [SafetyRule(id=r["id"], list_type=r["list_type"], platform=r["platform"],
                           username=r["username"], note=r["note"], created_at=r["created_at"])
                for r in rows]

    def delete_safety_rule(self, rule_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM safety_rules WHERE id=?", (rule_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ profiles
    def upsert_profile(self, profile: UserProfile) -> UserProfile:
        with self._conn() as c:
            c.execute(
                """INSERT INTO profiles (id, platform, username, data_json, first_seen, last_seen, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(platform, username) DO UPDATE SET
                     data_json=excluded.data_json, first_seen=excluded.first_seen,
                     last_seen=excluded.last_seen, updated_at=excluded.updated_at""",
                (profile.id, profile.platform, profile.username, dumps(profile.data),
                 profile.first_seen, profile.last_seen, profile.updated_at))
        return profile

    def get_profile(self, platform: str, username: str) -> Optional[UserProfile]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM profiles WHERE platform=? AND username=?",
                            (platform, username)).fetchone()
        if not row:
            return None
        return UserProfile(id=row["id"], platform=row["platform"], username=row["username"],
                           data=loads(row["data_json"], {}), first_seen=row["first_seen"],
                           last_seen=row["last_seen"], updated_at=row["updated_at"])

    def list_profiles(self, limit: int = 500) -> List[UserProfile]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM profiles ORDER BY updated_at DESC LIMIT ?",
                             (limit,)).fetchall()
        return [UserProfile(id=r["id"], platform=r["platform"], username=r["username"],
                            data=loads(r["data_json"], {}), first_seen=r["first_seen"],
                            last_seen=r["last_seen"], updated_at=r["updated_at"]) for r in rows]

    # --------------------------------------------------------------- feed sources
    def save_feed(self, feed: FeedSource) -> FeedSource:
        with self._conn() as c:
            c.execute("INSERT INTO feed_sources (id, data_json) VALUES (?,?) "
                      "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                      (feed.id, dumps(feed.to_dict())))
        return feed

    def list_feeds(self, only_enabled: bool = False) -> List[FeedSource]:
        with self._conn() as c:
            rows = c.execute("SELECT data_json FROM feed_sources ORDER BY id").fetchall()
        feeds = [FeedSource.from_dict(loads(r["data_json"])) for r in rows]
        if only_enabled:
            feeds = [f for f in feeds if f.enabled]
        return feeds

    def delete_feed(self, feed_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM feed_sources WHERE id=?", (feed_id,))
        return cur.rowcount > 0

    # -------------------------------------------------------------- monitors (mention/competitor)
    def save_monitor(self, kind: str, rule: Any) -> Any:
        with self._conn() as c:
            c.execute("INSERT INTO monitors (id, kind, data_json) VALUES (?,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, "
                      "data_json=excluded.data_json",
                      (rule.id, kind, dumps(rule.to_dict())))
        return rule

    def list_monitors(self, kind: Optional[str] = None, only_enabled: bool = False) -> List[Dict[str, Any]]:
        q = "SELECT kind, data_json FROM monitors"
        args: list = []
        if kind:
            q += " WHERE kind=?"
            args.append(kind)
        q += " ORDER BY id"
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        out = []
        for r in rows:
            data = loads(r["data_json"], {})
            rule = (MentionRule.from_dict(data) if r["kind"] == "mention"
                    else CompetitorRule.from_dict(data))
            if only_enabled and not rule.enabled:
                continue
            out.append({"kind": r["kind"], "rule": rule})
        return out

    def delete_monitor(self, monitor_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM monitors WHERE id=?", (monitor_id,))
        return cur.rowcount > 0

    # --------------------------------------------------------------- inbox rules
    def save_inbox_rule(self, rule: InboxRule) -> InboxRule:
        with self._conn() as c:
            c.execute("INSERT INTO inbox_rules (id, data_json) VALUES (?,?) "
                      "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                      (rule.id, dumps(rule.to_dict())))
        return rule

    def list_inbox_rules(self, only_enabled: bool = False) -> List[InboxRule]:
        with self._conn() as c:
            rows = c.execute("SELECT data_json FROM inbox_rules ORDER BY id").fetchall()
        rules = [InboxRule.from_dict(loads(r["data_json"])) for r in rows]
        if only_enabled:
            rules = [r for r in rules if r.enabled]
        return rules

    def delete_inbox_rule(self, rule_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM inbox_rules WHERE id=?", (rule_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------- trends
    def save_trend(self, platform: str, topic: str, source: str = "",
                   data: Optional[Dict[str, Any]] = None) -> str:
        tid = new_id("trd")
        with self._conn() as c:
            c.execute("INSERT INTO trends (id, platform, topic, source, captured_at, data_json) "
                      "VALUES (?,?,?,?,?,?)",
                      (tid, platform, topic, source, iso(utcnow()), dumps(data or {})))
        return tid

    def list_trends(self, platform: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        q = "SELECT * FROM trends"
        args: list = []
        if platform:
            q += " WHERE platform=?"
            args.append(platform)
        q += " ORDER BY captured_at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [{"id": r["id"], "platform": r["platform"], "topic": r["topic"],
                 "source": r["source"], "captured_at": r["captured_at"],
                 "data": loads(r["data_json"], {})} for r in rows]

    # ------------------------------------------------------------------ reports
    def save_report(self, month: str, data: Dict[str, Any]) -> str:
        rid = new_id("rep")
        with self._conn() as c:
            c.execute("INSERT INTO reports (id, month, data_json, created_at) VALUES (?,?,?,?) "
                      "ON CONFLICT(month) DO UPDATE SET data_json=excluded.data_json, "
                      "created_at=excluded.created_at",
                      (rid, month, dumps(data), iso(utcnow())))
        return rid

    def get_report(self, month: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT data_json FROM reports WHERE month=?", (month,)).fetchone()
        return loads(row["data_json"]) if row else None

    # --------------------------------------------------------------- seen items (dedupe)
    def mark_seen(self, kind: str, platform: str, remote_id: str) -> bool:
        """Record a processed item. Returns False when it was already seen."""
        try:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO seen_items (id, kind, platform, remote_id, ts) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(kind, remote_id) DO NOTHING",
                    (new_id("seen"), kind, platform, remote_id, iso(utcnow())))
                return cur.rowcount > 0
        except sqlite3.IntegrityError:  # pragma: no cover
            return False

    def is_seen(self, kind: str, remote_id: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT 1 FROM seen_items WHERE kind=? AND remote_id=?",
                            (kind, remote_id)).fetchone()
        return row is not None

    # ------------------------------------------------------------- rate limiter state
    def get_bucket(self, key: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM rate_buckets WHERE key=?", (key,)).fetchone()
        return {"tokens": row["tokens"], "last_refill": row["last_refill"]} if row else None

    def save_bucket(self, key: str, tokens: float, last_refill: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO rate_buckets (key, tokens, last_refill) VALUES (?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET tokens=excluded.tokens, "
                      "last_refill=excluded.last_refill",
                      (key, tokens, last_refill))
