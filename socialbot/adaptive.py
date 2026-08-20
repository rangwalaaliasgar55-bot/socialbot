"""Self-learning loop — best-time-to-post, vibe matching and adaptive hashtags.

Everything is derived from the engagement data SocialBot already records
(``metrics`` + post timestamps), so the more you post, the smarter the
suggestions get — no premium tier, no external services.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from . import intelligence as nlp
from .models import iso, parse_dt, utcnow
from .storage import Store

log = logging.getLogger("socialbot.adaptive")


def _engagement_value(metrics: Dict[str, Any]) -> float:
    m = metrics or {}
    return (float(m.get("likes", 0)) + float(m.get("shares", 0)) * 2
            + float(m.get("comments", 0)) * 3 + float(m.get("impressions", 0)) / 100)


def best_times(store: Store, platform: Optional[str] = None,
               min_posts: int = 5) -> List[Dict[str, Any]]:
    """Rank (weekday, hour) engagement windows from post history.

    Returns a list of windows with engagement per post, best first. Empty when
    there isn't enough history yet.
    """
    posts = store.list_posts(limit=2000)
    buckets: Dict[tuple, List[float]] = defaultdict(list)
    for post in posts:
        if post.status not in ("published", "partial") or not post.published_at:
            continue
        ts = parse_dt(post.published_at)
        if not ts:
            continue
        for platform_name, result in (post.results or {}).items():
            if platform and platform_name != platform:
                continue
            if not result.get("ok"):
                continue
            latest = [r for r in store.latest_metrics(post.id, limit=5)
                      if r["platform"] == platform_name]
            value = _engagement_value(latest[0]["metrics"]) if latest else 0.0
            buckets[(ts.weekday(), ts.hour)].append(value)

    ranked = []
    for (weekday, hour), values in buckets.items():
        ranked.append({"weekday": weekday, "hour": hour,
                       "posts": len(values),
                       "avg_engagement": sum(values) / len(values)})
    ranked.sort(key=lambda w: (-w["avg_engagement"], -w["posts"]))
    return ranked if len(buckets) >= min_posts else []


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def human_window(window: Dict[str, Any]) -> str:
    return f"{WEEKDAYS[window['weekday']]} {window['hour']:02d}:00"


def suggest_time(store: Store, platform: Optional[str] = None,
                 now: Optional[datetime] = None,
                 min_posts: int = 2) -> Optional[str]:
    """Earliest high-engagement window at/after *now* (ISO UTC), or None.

    Returns None when there's no history — callers then fall back to a sane
    default (e.g. +1h) so scheduling always works.
    """
    windows = best_times(store, platform, min_posts=min_posts)
    if not windows:
        return None
    now = now or utcnow()
    for window in windows:
        candidate = now.replace(hour=window["hour"], minute=0, second=0, microsecond=0)
        delta = (window["weekday"] - candidate.weekday()) % 7
        candidate += timedelta(days=delta)
        if candidate < now:
            candidate += timedelta(days=7)
        return iso(candidate)
    return None


def vibe_fit(store: Store, text: str, platform: Optional[str] = None) -> Dict[str, Any]:
    """Score how well *text* matches the style of your best-performing posts.

    Returns a 0-100 fit score plus concrete suggestions.
    """
    posts = store.list_posts(limit=2000)
    scored: List[tuple] = []
    for post in posts:
        if post.status not in ("published", "partial"):
            continue
        if platform and platform not in (post.platforms or []):
            continue
        value = 0.0
        for platform_name, result in (post.results or {}).items():
            if not result.get("ok"):
                continue
            latest = [r for r in store.latest_metrics(post.id, limit=5)
                      if r["platform"] == platform_name]
            value += _engagement_value(latest[0]["metrics"]) if latest else 0.0
        scored.append((value, post))
    if not scored:
        return {"fit": 50, "posts_compared": 0, "suggestions": [
            "Post more and refresh metrics to get personalised style feedback."]}

    scored.sort(key=lambda t: -t[0])
    top = [post for _, post in scored[:max(3, len(scored) // 4)]]
    candidate = nlp.vibe_metrics(text)
    suggestions: List[str] = []

    best_length = sum(len(p.text) for p in top) / len(top)
    if candidate["length"] > best_length * 1.6:
        suggestions.append(f"Your best posts average ~{int(best_length)} chars — try trimming.")
    elif candidate["length"] < max(40, best_length * 0.5):
        suggestions.append("Your best posts are a bit longer — add a little more substance.")

    top_hashtags = sorted({len(re.findall(r"#\w+", p.text)) for p in top})
    median_tags = top_hashtags[len(top_hashtags) // 2] if top_hashtags else 0
    if candidate["hashtags"] > median_tags + 3:
        suggestions.append(f"You usually use ~{median_tags} hashtags — fewer feels more human.")
    elif median_tags and candidate["hashtags"] < median_tags - 2:
        suggestions.append(f"You usually use ~{median_tags} hashtags — a couple more helps reach.")

    top_sent = sum(nlp.sentiment(p.text) for p in top) / len(top)
    if candidate["sentiment"] < top_sent - 0.3:
        suggestions.append("Your best posts skew more positive — try a warmer opening.")
    if candidate["questions"] == 0:
        suggestions.append("A question at the end tends to boost engagement for you.")
    if not suggestions:
        suggestions.append("This matches your best-performing style — ship it!")

    closeness = 0.0
    for key in ("questions", "exclamations", "hashtags", "emoji"):
        vals = [nlp.vibe_metrics(p.text)[key] for p in top]
        avg = sum(vals) / len(vals)
        if avg > 0:
            closeness += min(1.0, candidate[key] / avg) / 4
        elif candidate[key] == 0:
            closeness += 0.25
    fit = int(round(50 + closeness * 50))
    return {"fit": max(0, min(100, fit)), "posts_compared": len(scored),
            "suggestions": suggestions[:3]}


def adaptive_hashtags(store: Store, topic: str, platform: Optional[str] = None,
                      n: int = 3) -> List[str]:
    """Recommend hashtags from your best posts, blended with the topic."""
    posts = store.list_posts(limit=2000)
    usage: Dict[str, float] = defaultdict(float)
    for post in posts:
        if post.status not in ("published", "partial"):
            continue
        if platform and platform not in (post.platforms or []):
            continue
        value = 0.0
        for platform_name, result in (post.results or {}).items():
            if not result.get("ok"):
                continue
            latest = [r for r in store.latest_metrics(post.id, limit=5)
                      if r["platform"] == platform_name]
            value += _engagement_value(latest[0]["metrics"]) if latest else 0.0
        for tag in re.findall(r"#(\w+)", post.text):
            usage[tag] += 1 + value / 10

    from . import ai as ai_mod
    topic_tags = [t.lstrip("#").lower() for t in ai_mod.hashtags_for(topic, 2)]
    recommended = [f"#{tag}" for tag, _ in sorted(usage.items(),
                                                  key=lambda kv: -kv[1])[:n]]
    for tag in topic_tags:
        if len(recommended) >= n:
            break
        if tag not in [t.lstrip("#") for t in recommended]:
            recommended.append(f"#{tag}")
    return recommended[:n]


def schedule_summary(store: Store) -> Dict[str, Any]:
    """Everything the Insights tab needs in one call."""
    windows = best_times(store)
    return {
        "windows": windows[:8],
        "windows_human": [human_window(w) for w in windows[:8]],
        "has_history": bool(windows),
        "platforms": sorted({p for p in
                             [r["platform"] for row in store.latest_metrics()]})[:20],
    }