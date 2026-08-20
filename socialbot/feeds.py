"""Content sources — RSS feeds, curated lists and platform trends.

``fetch_rss`` pulls items from any RSS 2.0 / Atom feed (stdlib XML parsing —
no extra dependency), and the suggestion helpers turn raw items into real
post drafts with hooks and hashtags. Trend capture is platform-driven: any
provider can expose a ``get_trending`` capability (mock does).
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .http import HttpClient
from .models import Post, PostStatus, iso, utcnow
from .platforms import PlatformError, create_platform
from .storage import Store

log = logging.getLogger("socialbot.feeds")


def fetch_rss(url: str, http: Optional[HttpClient] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch and parse an RSS 2.0 or Atom feed into item dicts.

    Each item: ``{"title", "link", "summary", "source", "published"}``.
    Raises ``PlatformError`` on network/parse failures.
    """
    client = http or HttpClient(timeout=30)
    try:
        resp = client.session.get(url, timeout=30)
    except Exception as exc:
        raise PlatformError(f"could not fetch feed {url}: {exc}")
    if resp.status_code >= 400:
        raise PlatformError(f"feed {url}: HTTP {resp.status_code}")
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise PlatformError(f"feed {url} is not valid XML: {exc}")

    items: List[Dict[str, Any]] = []
    source = (root.findtext("./channel/title") or root.findtext("./{*}title")
              or urlparse(url).netloc or url)[:120]

    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        def text(name: str) -> str:
            el = node.find(name)
            if el is None:
                el = node.find(f"{{*}}{name}")
            return (el.text or "").strip() if el is not None else ""

        items.append({
            "title": text("title"),
            "link": text("link") or "",
            "summary": text("description") or text("summary") or "",
            "source": source,
            "published": text("pubDate") or text("published") or "",
        })
        if len(items) >= limit:
            break
    return items


def suggest_from_items(items: List[Dict[str, Any]], n: int = 3,
                       platforms: Optional[List[str]] = None,
                       http: Optional[HttpClient] = None) -> List[Post]:
    """Turn feed items into ready-to-schedule draft posts.

    Combines a hook, the item title/summary and a link, then saves drafts into
    the store (origin ``feed:<source>``) so they show up in the calendar queue.
    """
    from . import ai as ai_mod

    drafts: List[Post] = []
    seen: set = set()
    for item in items:
        title = item.get("title") or item.get("summary", "")[:60]
        if not title or title in seen:
            continue
        seen.add(title)
        topic = re.sub(r"\s+", " ", title)[:80]
        hook = (ai_mod.HOOKS or ["About {topic}:"])[len(drafts) % len(ai_mod.HOOKS)]
        text = f"{hook.format(topic=topic)}\n\n{item.get('summary', '')[:220]}"
        if item.get("link"):
            text += f"\n\n{item['link']}"
        hashtags = " ".join(ai_mod.hashtags_for(topic, 3))
        text += f"\n{hashtags}"
        drafts.append(Post(text=text.strip(), platforms=platforms or [],
                           status=PostStatus.DRAFT.value, origin=f"feed:{item.get('source', '')[:40]}"))
        if len(drafts) >= n:
            break
    return drafts


def run_feed(feed: Any, store: Store, http: Optional[HttpClient] = None) -> Dict[str, Any]:
    """Pull one feed source and (optionally) create drafts from new items."""
    http = http or HttpClient()
    try:
        if feed.kind == "rss":
            if not feed.url:
                raise PlatformError("rss feed needs a url")
            items = fetch_rss(feed.url, http, limit=10)
        else:
            items = list(feed.items or [])
    except PlatformError as exc:
        feed.last_run, feed.last_result = iso(utcnow()), {"ok": False, "error": str(exc)}
        store.save_feed(feed)
        return feed.last_result

    fresh: List[Dict[str, Any]] = []
    for item in items:
        key = item.get("link") or item.get("title") or ""
        if key and store.mark_seen(f"feed:{feed.id}", "rss", key):
            fresh.append(item)

    created = 0
    if feed.auto_draft and fresh:
        drafts = suggest_from_items(fresh, n=feed.n_drafts,
                                    platforms=feed.target_platforms, http=http)
        for draft in drafts:
            draft.origin = f"feed:{feed.name}"
            store.save_post(draft)
        created = len(drafts)

    feed.last_run = iso(utcnow())
    feed.last_result = {"ok": True, "items": len(items), "new": len(fresh),
                        "drafts": created}
    store.save_feed(feed)
    store.log_event("feed.pull", f"feed '{feed.name}': {len(items)} items, "
                                 f"{len(fresh)} new, {created} drafts",
                    {"feed_id": feed.id, "new": len(fresh), "drafts": created})
    return feed.last_result


def capture_trends(store: Store, http: Optional[HttpClient] = None,
                   create_drafts: bool = True) -> List[Dict[str, Any]]:
    """Capture trending topics from every connected platform that supports it.

    Trends are stored and (by default) turned into draft posts tagged "trend",
    so you can ride the wave naturally.
    """
    http = http or HttpClient()
    reports: List[Dict[str, Any]] = []
    for account in store.list_accounts():
        platform_name = account["platform"]
        try:
            platform = create_platform(platform_name, account.get("config", {}), http)
            if "trending" not in platform.capabilities:
                continue
            trends = platform.get_trending(limit=10)
        except (PlatformError, NotImplementedError) as exc:
            reports.append({"platform": platform_name, "ok": False, "error": str(exc)})
            continue

        captured = 0
        for topic in trends:
            name = topic.get("topic") or topic.get("name") or ""
            if not name:
                continue
            key = f"{platform_name}:{name.lower().strip()}"
            if store.is_seen("trend", key):
                continue
            store.mark_seen("trend", platform_name, key)
            store.save_trend(platform_name, name, topic.get("source", "trending"),
                             {"score": topic.get("score"), "url": topic.get("url")})
            captured += 1
            if create_drafts:
                from . import ai as ai_mod
                draft_text = ai_mod.generate(name, n=1)[0]["text"]
                draft = Post(text=draft_text, platforms=[], status=PostStatus.DRAFT.value,
                             tag="trend", origin=f"trend:{platform_name}:{name}")
                store.save_post(draft)
        reports.append({"platform": platform_name, "ok": True,
                        "captured": captured, "total": len(trends)})
    if reports:
        ok = sum(1 for r in reports if r.get("ok"))
        store.log_event("trends.capture", f"captured trends from {ok} platform(s): "
                                          f"{', '.join(r['platform'] for r in reports)}",
                        {"reports": reports})
    return reports