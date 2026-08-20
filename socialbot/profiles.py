"""User profiling — build interest/activity profiles of engaged users.

Every interaction (bot action, mention monitor, inbox reply) feeds the profile
store. The smart-engagement agent then uses these profiles to find *similar*
users worth targeting, so growth is aimed at people who already care about
your niche.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import intelligence as nlp
from .models import UserProfile, iso, parse_dt, utcnow
from .storage import Store

log = logging.getLogger("socialbot.profiles")


def observe(store: Store, platform: str, username: str, text: str = "",
            action: str = "engage") -> UserProfile:
    """Update (or create) the profile for *username* after an interaction."""
    username = (username or "").lstrip("@")
    if not username:
        profile = UserProfile(platform=platform, username=username)
        store.upsert_profile(profile)
        return profile

    profile = store.get_profile(platform, username)
    now = iso(utcnow())
    if profile is None:
        profile = UserProfile(platform=platform, username=username,
                              data={"interests": [], "activity_hours": {},
                                    "actions": {}, "posts_seen": 0},
                              first_seen=now, last_seen=now, updated_at=now)
    else:
        profile.updated_at = now
        profile.last_seen = now
        if not profile.first_seen:
            profile.first_seen = now

    data = profile.data
    data["posts_seen"] = int(data.get("posts_seen", 0)) + 1
    counts = data.setdefault("actions", {})
    counts[action] = int(counts.get(action, 0)) + 1

    if text:
        topics = nlp.topics(text, 5)
        interests = set(data.get("interests", []))
        interests.update(topics)
        data["interests"] = sorted(interests)[:30]

        now_dt = parse_dt(now) or utcnow()
        hour = f"{now_dt.hour:02d}"
        hours = data.setdefault("activity_hours", {})
        hours[hour] = int(hours.get(hour, 0)) + 1

        score = nlp.sentiment(text)
        data["last_sentiment"] = round(score, 3)

    store.upsert_profile(profile)
    return profile


def find_similar(store: Store, interests: List[str], platform: Optional[str] = None,
                 exclude: Optional[List[str]] = None, limit: int = 10,
                 min_posts_seen: int = 1) -> List[UserProfile]:
    """Rank profiles by interest overlap with *interests*.

    The smart-engagement agent uses this to find users worth following/liking —
    people who already talk about your niche.
    """
    want = set(i.lower() for i in (interests or []) if i)
    if not want:
        return []
    exclude = set((exclude or []))
    scored: List[tuple] = []
    for profile in store.list_profiles(limit=500):
        if profile.username in exclude:
            continue
        if platform and profile.platform != platform:
            continue
        have = set(i.lower() for i in profile.data.get("interests", []))
        overlap = len(want & have)
        if overlap <= 0:
            continue
        if profile.data.get("posts_seen", 0) < min_posts_seen:
            continue
        scored.append((overlap, profile.data.get("posts_seen", 0), profile))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [profile for _, _, profile in scored[:limit]]


def similar_targets(store: Store, platform: str, interests: List[str],
                    limit: int = 10) -> List[Dict[str, Any]]:
    """Usernames + interest summary for targeting, as dicts for the API."""
    out = []
    for profile in find_similar(store, interests, platform=platform, limit=limit):
        out.append({
            "platform": profile.platform,
            "username": profile.username,
            "interests": profile.data.get("interests", [])[:6],
            "posts_seen": profile.data.get("posts_seen", 0),
            "actions": profile.data.get("actions", {}),
            "last_sentiment": profile.data.get("last_sentiment"),
            "last_seen": profile.last_seen,
        })
    return out