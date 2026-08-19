"""Analytics — collect per-post engagement metrics over time, aggregate and export."""
from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .http import HttpClient
from .platforms import PlatformError, create_platform
from .storage import Store

log = logging.getLogger("socialbot.analytics")


def refresh_metrics(store: Store, http: Optional[HttpClient] = None,
                    limit: int = 100) -> int:
    """Pull latest numbers for every published post that supports metrics."""
    client = http or HttpClient()
    updated = 0
    for post in store.list_posts(limit=limit):
        if post.status not in ("published", "partial"):
            continue
        for platform_name, result in (post.results or {}).items():
            if not result.get("ok") or not result.get("remote_id"):
                continue
            try:
                account = store.get_account(platform_name)
                platform = create_platform(platform_name,
                                           (account or {}).get("config", {}), client)
                if "metrics" not in platform.capabilities:
                    continue
                metrics = platform.get_metrics(result["remote_id"])
                if metrics:
                    store.save_metrics(post.id, platform_name, result["remote_id"], metrics)
                    updated += 1
            except PlatformError as exc:
                log.debug("metrics %s/%s: %s", post.id, platform_name, exc)
            except Exception as exc:  # pragma: no cover
                log.debug("metrics %s/%s crashed: %s", post.id, platform_name, exc)
    return updated


def summary(store: Store) -> Dict[str, Any]:
    """Aggregate analytics for dashboard/CLI."""
    posts = store.list_posts(limit=1000)
    by_status: Dict[str, int] = defaultdict(int)
    by_platform: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    published_window: List[str] = []

    for p in posts:
        by_status[p.status] += 1
        for platform, result in (p.results or {}).items():
            by_platform[platform]["total"] += 1
            by_platform[platform]["ok"] += 1 if result.get("ok") else 0
        if p.published_at:
            published_window.append(p.published_at)

    # engagement totals from latest metric snapshots
    engagement: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in store.latest_metrics():
        platform = row["platform"]
        for key, value in (row["metrics"] or {}).items():
            if isinstance(value, (int, float)):
                engagement[platform][key] += value

    return {
        "total_posts": len(posts),
        "by_status": dict(by_status),
        "by_platform": {k: dict(v) for k, v in by_platform.items()},
        "engagement": {k: dict(v) for k, v in engagement.items()},
        "latest_metrics": store.latest_metrics(limit=100),
    }


def to_csv(store: Store) -> str:
    """Render per-post latest metrics as CSV (for exports/reports)."""
    posts = {p.id: p for p in store.list_posts(limit=1000)}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["post_id", "published_at", "platform", "remote_id",
                     "likes", "shares", "comments", "impressions", "text_preview"])
    for row in store.latest_metrics():
        post = posts.get(row["post_id"])
        m = row["metrics"] or {}
        writer.writerow([row["post_id"],
                         (post.published_at if post else ""),
                         row["platform"], row["remote_id"] or "",
                         m.get("likes", ""), m.get("shares", ""), m.get("comments", ""),
                         m.get("impressions", ""),
                         (post.text[:60] if post else "").replace("\n", " ")])
    return buf.getvalue()
