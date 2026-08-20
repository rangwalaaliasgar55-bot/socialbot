"""Monthly growth report — a built-in summary, no premium tier needed.

Pulls posts, metrics, agent activity and profiles for a given month and renders
a friendly text/markdown report. Optionally delivered via webhook so it lands
in Slack/Discord/n8n automatically.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .models import iso, parse_dt, utcnow
from .storage import Store
from .webhooks import fire_webhook

log = logging.getLogger("socialbot.reports")

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def _month_bounds(month: str) -> tuple:
    """Return (start_dt, end_dt) for 'YYYY-MM' (aware UTC datetimes)."""
    year, m = int(month[:4]), int(month[5:7])
    start = datetime(year, m, 1, tzinfo=timezone.utc)
    end = datetime(year + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1,
                   tzinfo=timezone.utc)
    return start, end


def monthly_report(store: Store, month: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate everything that happened in *month* (default: last month)."""
    now = utcnow()
    if month:
        start, end = _month_bounds(month)
    else:
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first
        start = (first - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0,
                                                    microsecond=0)
        month = f"{start.year:04d}-{start.month:02d}"

    posts = store.list_posts(limit=5000)
    month_posts = [p for p in posts if p.published_at and start <= parse_dt(p.published_at) < end]
    prev_posts = [p for p in posts if p.published_at and end - timedelta(days=35) <=
                  parse_dt(p.published_at) < start]

    by_platform: Dict[str, int] = defaultdict(int)
    total_likes = total_comments = total_shares = total_impressions = 0
    top: List[tuple] = []
    for post in month_posts:
        value = 0.0
        for platform_name, result in (post.results or {}).items():
            if not result.get("ok"):
                continue
            by_platform[platform_name] += 1
            latest = [r for r in store.latest_metrics(post.id, limit=5)
                      if r["platform"] == platform_name]
            if latest:
                m = latest[0]["metrics"] or {}
                total_likes += int(m.get("likes", 0))
                total_comments += int(m.get("comments", 0))
                total_shares += int(m.get("shares", 0))
                total_impressions += int(m.get("impressions", 0))
                value += (int(m.get("likes", 0)) + int(m.get("comments", 0)) * 3
                          + int(m.get("shares", 0)) * 2)
        top.append((value, post))

    top.sort(key=lambda t: -t[0])
    agent_events: Dict[str, int] = defaultdict(int)
    engagement_events = 0
    for event in store.list_events(limit=2000):
        ts = parse_dt(event["ts"])
        if not ts or not (start <= ts < end):
            continue
        agent_events[event["type"]] += 1
        if event["type"] in ("bot.run", "agent.mention", "agent.competitor"):
            data = event.get("data") or {}
            engagement_events += int(data.get("acted", 0)) + int(data.get("engaged", 0))

    profiles = [p for p in store.list_profiles(limit=1000)
                if p.last_seen and start <= parse_dt(p.last_seen) < end]

    followers_gained = sum(int(p.data.get("actions", {}).get("follow", 0))
                           for p in profiles)
    post_growth = len(month_posts) - len(prev_posts)

    return {
        "month": month,
        "generated_at": iso(now),
        "posts_published": len(month_posts),
        "posts_growth": post_growth,
        "by_platform": dict(by_platform),
        "engagement": {"likes": total_likes, "comments": total_comments,
                       "shares": total_shares, "impressions": total_impressions},
        "top_posts": [{"id": p.id, "text": p.text[:120],
                       "platforms": p.platforms,
                       "published_at": p.published_at}
                      for _, p in top[:5]],
        "new_profiles_engaged": len(profiles),
        "follows_gained": followers_gained,
        "agent_activity": dict(agent_events),
        "engagement_actions": engagement_events,
    }


def render_report(data: Dict[str, Any]) -> str:
    """Render the report as readable markdown/text."""
    m = data
    lines = [
        f"# 📈 SocialBot growth report — {m['month']}",
        "",
        f"Generated {m['generated_at']}",
        "",
        "## Highlights",
        f"- **{m['posts_published']}** posts published "
        f"({m['posts_growth']:+d} vs previous month)",
        f"- **{m['engagement']['likes']}** likes, **{m['engagement']['comments']}** comments, "
        f"**{m['engagement']['shares']}** shares, **{m['engagement']['impressions']}** impressions",
        f"- **{m['new_profiles_engaged']}** new users engaged, "
        f"**{m['follows_gained']}** follows gained",
        f"- **{m['engagement_actions']}** engagement actions performed by agents",
        "",
        "## By platform",
    ]
    for platform_name, count in sorted(m["by_platform"].items()):
        lines.append(f"- {platform_name}: {count} posts")
    lines += ["", "## Top posts"]
    for post in m["top_posts"]:
        lines.append(f"- {post['published_at'][:10]} · {', '.join(post['platforms'])} · "
                     f"{post['text'][:90]}…")
    lines += ["", "## Agent activity"]
    if m["agent_activity"]:
        for type_, count in sorted(m["agent_activity"].items()):
            lines.append(f"- {type_}: {count}")
    else:
        lines.append("- no agent runs this month")
    return "\n".join(lines)


def save_and_deliver(store: Store, month: Optional[str] = None,
                     webhook: Optional[str] = None) -> Dict[str, Any]:
    """Generate, store and optionally webhook the report."""
    report = monthly_report(store, month)
    store.save_report(report["month"], report)
    if webhook:
        fire_webhook(webhook, _as_post_like(report))
    store.log_event("report.monthly", f"monthly report generated for {report['month']}",
                    {"month": report["month"]})
    return report


def _as_post_like(report: Dict[str, Any]) -> Any:
    """Webhooks expect a Post-ish payload; build a minimal stand-in."""
    from .models import Post
    return Post(text=render_report(report)[:2000], platforms=[], tag="report",
                published_at=report["generated_at"])