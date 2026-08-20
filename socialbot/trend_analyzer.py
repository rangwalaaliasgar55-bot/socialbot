"""Real-time trend analysis — Twitter/X + Reddit sources with mock fallback.

Ported from PR #3 and reconciled with the v1.2.0 trend pipeline:

- Fetches live trending topics from Twitter/X (Bearer token) and Reddit
  (OAuth client credentials) when configured
- Scores sentiment with the offline NLP lexicon (``socialbot.intelligence``)
- Falls back to seeded demo trends so the whole flow works without credentials
- Produces content strategies that can be turned into drafts immediately

Use it directly, or via :func:`socialbot.feeds.capture_trends` which merges
these real-world sources with platform-native trending.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from . import intelligence as nlp

logger = logging.getLogger("socialbot.trend_analyzer")

TWITTER_TRENDS_URL = "https://api.twitter.com/1.1/trends/place.json"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_HOT_URL = "https://oauth.reddit.com/r/all/hot.json"

# Demo topics used when no provider is configured (mirrors PR #3).
DEMO_TRENDS = [
    {"topic": "AI in Healthcare", "volume": 150000, "growth_rate": 0.45,
     "sentiment": "positive", "platforms": ["twitter", "linkedin"],
     "related_keywords": ["machinelearning", "healthtech", "innovation"]},
    {"topic": "Remote Work Tools", "volume": 89000, "growth_rate": 0.22,
     "sentiment": "neutral", "platforms": ["linkedin", "twitter", "facebook"],
     "related_keywords": ["productivity", "wfh", "collaboration"]},
    {"topic": "Sustainable Living", "volume": 210000, "growth_rate": 0.67,
     "sentiment": "positive", "platforms": ["instagram", "threads", "facebook"],
     "related_keywords": ["ecofriendly", "zerowaste", "climateaction"]},
]

# Best-practice posting windows per platform (production: use analytics data).
OPTIMAL_TIMES = {
    "twitter": "09:00 AM", "x": "09:00 AM", "linkedin": "08:00 AM",
    "instagram": "06:00 PM", "facebook": "01:00 PM", "threads": "07:00 PM",
    "tiktok": "07:00 PM", "youtube": "04:00 PM",
}


@dataclass
class TrendData:
    """A trending topic with volume, growth and sentiment context."""

    topic: str
    volume: int
    growth_rate: float
    sentiment: str  # positive, neutral, negative
    platforms: List[str]
    related_keywords: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic, "volume": self.volume,
            "growth_rate": self.growth_rate, "sentiment": self.sentiment,
            "platforms": self.platforms, "related_keywords": self.related_keywords,
        }


class RealTrendAnalyzer:
    """Aggregates trends from Twitter/X and Reddit (mock fallback when unset)."""

    def __init__(self, session: Optional[requests.Session] = None,
                 twitter_bearer: Optional[str] = None,
                 reddit_client_id: Optional[str] = None,
                 reddit_secret: Optional[str] = None):
        self.session = session or requests.Session()
        self.twitter_bearer = twitter_bearer or os.getenv("TWITTER_BEARER_TOKEN")
        self.reddit_client_id = reddit_client_id or os.getenv("REDDIT_CLIENT_ID")
        self.reddit_secret = reddit_secret or os.getenv("REDDIT_SECRET")

    # ------------------------------------------------------------------ sources
    def fetch_twitter_trends(self, woeid: int = 1) -> List[Dict[str, Any]]:
        if not self.twitter_bearer:
            logger.warning("TWITTER_BEARER_TOKEN not configured — using mock data")
            return []
        try:
            resp = self.session.get(TWITTER_TRENDS_URL, params={"id": woeid},
                                    headers={"Authorization": f"Bearer {self.twitter_bearer}"},
                                    timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return (data[0] or {}).get("trends", []) if isinstance(data, list) and data else []
        except Exception as e:
            logger.error("twitter trend fetch failed: %s", e)
            return []

    def fetch_reddit_hot_topics(self, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.reddit_client_id:
            logger.warning("REDDIT_CLIENT_ID not configured — using mock data")
            return []
        try:
            auth = requests.auth.HTTPBasicAuth(self.reddit_client_id, self.reddit_secret)
            token_resp = self.session.post(REDDIT_TOKEN_URL, auth=auth,
                                           data={"grant_type": "client_credentials"},
                                           timeout=10)
            token = token_resp.json().get("access_token")
            if not token:
                return []
            resp = self.session.get(REDDIT_HOT_URL,
                                    headers={"Authorization": f"Bearer {token}",
                                             "User-Agent": "SocialBot/1.0"},
                                    params={"limit": limit}, timeout=10)
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            topics = []
            for post in posts[:5]:
                d = post["data"]
                flair = (d.get("link_flair_text") or "").split(",")
                topics.append({
                    "topic": d["title"], "volume": d.get("ups", 0),
                    "growth_rate": 0.1, "sentiment": "neutral",
                    "platforms": ["reddit"],
                    "related_keywords": [f.strip() for f in flair if f.strip()],
                })
            return topics
        except Exception as e:
            logger.error("reddit topic fetch failed: %s", e)
            return []

    # ------------------------------------------------------------------- usage
    def get_trending_topics(self, platform: Optional[str] = None,
                            limit: int = 10) -> List[TrendData]:
        """Aggregate trends from all configured sources, ranked by volume."""
        all_trends: List[TrendData] = []
        for trend in self.fetch_twitter_trends():
            name = trend.get("name", "")
            if not name:
                continue
            all_trends.append(TrendData(
                topic=name,
                volume=trend.get("tweet_volume") or 0,
                growth_rate=0.1,
                sentiment=nlp.sentiment_label(nlp.sentiment(name)),
                platforms=["twitter"],
                related_keywords=[],
            ))
        all_trends.extend(TrendData(
            topic=t["topic"], volume=t["volume"], growth_rate=t["growth_rate"],
            sentiment=t["sentiment"], platforms=t["platforms"],
            related_keywords=t["related_keywords"],
        ) for t in self.fetch_reddit_hot_topics())

        if not all_trends:
            logger.info("no provider configured — using demo trending data")
            all_trends = [TrendData(**t) for t in DEMO_TRENDS]

        if platform:
            all_trends = [t for t in all_trends if platform in t.platforms]

        all_trends.sort(key=lambda x: x.volume * (1 + x.growth_rate), reverse=True)
        return all_trends[:limit]

    def generate_content_strategy(self, platform: str) -> Dict[str, Any]:
        """Build a ready-to-use content strategy from the top trend."""
        trends = self.get_trending_topics(platform, limit=1)
        if not trends:
            return {"error": "no trends available"}
        top = trends[0]
        return {
            "recommended_topic": top.topic,
            "tone": "professional" if platform == "linkedin" else "conversational",
            "target_audience": ("industry professionals" if platform == "linkedin"
                                else "general audience"),
            "trending_keywords": top.related_keywords or [top.topic.replace(" ", "")],
            "seo_goal": "engagement" if top.sentiment == "positive" else "awareness",
            "sentiment_context": top.sentiment,
            "trend_volume": top.volume,
            "optimal_posting_time": OPTIMAL_TIMES.get(platform, "12:00 PM"),
        }

    def capture(self, store: Any, create_drafts: bool = True,
                platform_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Save the latest trends into the store (and optionally draft posts).

        Mirrors the store interaction used by ``feeds.capture_trends`` so the
        results show up in the dashboard and trends list.
        """
        trends = self.get_trending_topics(platform_filter)
        captured = 0
        drafts_created = 0
        for trend in trends:
            key = f"real:{trend.topic.lower().strip()}"
            if store.is_seen("trend", key):
                continue
            store.mark_seen("trend", "trend-analyzer", key)
            store.save_trend("trend-analyzer", trend.topic, "real-time",
                             {"score": round(trend.volume * (1 + trend.growth_rate)),
                              "sentiment": trend.sentiment})
            captured += 1
            if create_drafts:
                from . import ai as ai_mod
                draft_text = ai_mod.generate(trend.topic, n=1)[0]["text"]
                from .models import Post, PostStatus
                store.save_post(Post(text=draft_text, platforms=[],
                                     status=PostStatus.DRAFT.value, tag="trend",
                                     origin=f"trend:real:{trend.topic}",
                                     review_status="pending"))
                drafts_created += 1
        if captured:
            store.log_event("trends.capture", f"trend analyzer: {captured} new trend(s), "
                                              f"{drafts_created} draft(s)",
                            {"captured": captured, "drafts": drafts_created})
        return [{"platform": "trend-analyzer", "ok": True, "captured": captured,
                 "drafts": drafts_created, "total": len(trends)}]