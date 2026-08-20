"""Tests for the new feature set: intelligence, safety, threads, feeds, agents,
profiles, adaptive engine and reports."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from socialbot import intelligence as nlp
from socialbot import profiles as profiles_mod
from socialbot.agents import AgentEngine
from socialbot.models import (BotRule, CompetitorRule, FeedSource, InboxRule,
                              MentionRule, Post, PostStatus, iso, utcnow)
from socialbot.publisher import Publisher
from socialbot.safety import RateLimiter, Safety
from socialbot.scheduler import Scheduler
from socialbot.threads import split_thread
from socialbot import adaptive


# ------------------------------------------------------------------- threads
def test_split_thread_short_text():
    assert split_thread("short post", 280) == ["short post"]


def test_split_thread_long_text():
    text = "First sentence about things. Second sentence goes on and on. " * 20
    parts = split_thread(text, max_length=80)
    assert len(parts) > 1
    assert all(len(p) <= 80 for p in parts)
    assert parts[0].startswith("1/")


def test_split_thread_hard_words():
    text = "word " * 200
    parts = split_thread(text, max_length=50)
    assert all(len(p) <= 50 for p in parts)


# ---------------------------------------------------------------- intelligence
def test_sentiment_scores():
    assert nlp.sentiment("I love this amazing product!") > 0.3
    assert nlp.sentiment("This is terrible and awful") < -0.3
    assert abs(nlp.sentiment("the cat sat on the mat")) < 0.3


def test_intent_detection():
    assert nlp.detect_intent("How much does pricing cost?") == "pricing"
    assert nlp.detect_intent("can I get a demo this week") == "demo"
    assert nlp.detect_intent("thanks so much!") == "thanks"
    assert nlp.detect_intent("this is broken, refund please") == "complaint"
    assert nlp.detect_intent("buy now free money click here") == "spam"


def test_reply_for_context():
    reply = nlp.reply_for("This is broken, I want a refund")
    assert "sorry" in reply.lower()
    reply = nlp.reply_for("thanks for the great service!")
    assert "appreciate" in reply.lower()


def test_topics_extract():
    topics = nlp.topics("python automation for social media growth python")
    assert "python" in topics


# -------------------------------------------------------------------- safety
def test_rate_limiter(store):
    limiter = RateLimiter(store, per_minute=2)
    assert limiter.allow("rate:mock:like")
    assert limiter.allow("rate:mock:like")
    assert not limiter.allow("rate:mock:like")
    assert limiter.allow("rate:mock:follow")  # separate key


def test_blacklist_whitelist(store):
    safety = Safety(store)
    safety.add("blacklist", "mock", "spammer", "spam")
    safety.add("whitelist", "mock", "fan")
    assert not safety.allowed("mock", "spammer", skip_blacklisted=True)
    assert safety.allowed("mock", "fan", whitelist_only=True)
    assert not safety.allowed("mock", "stranger", whitelist_only=True)
    assert safety.allowed("mock", "anyone")


# -------------------------------------------------------------------- adaptive
def test_best_times_and_suggest(store):
    store.save_account("mock", {})
    for hour in (8, 8, 9):
        post = Post(text="hi", platforms=["mock"], status="published",
                    published_at=iso(utcnow().replace(hour=hour)),
                    results={"mock": {"ok": True, "remote_id": "mock_1"}})
        store.save_post(post)
        store.save_metrics(post.id, "mock", "mock_1",
                           {"likes": 10, "comments": 5, "impressions": 1000})
    windows = adaptive.best_times(store, min_posts=2)
    assert windows and windows[0]["hour"] in (8, 9)
    assert adaptive.suggest_time(store) is not None


def test_vibe_fit_and_hashtags(store):
    post = Post(text="great post #growth #marketing", platforms=["mock"],
                status="published", published_at=iso(utcnow()))
    store.save_post(post)
    store.save_metrics(post.id, "mock", "mock_1", {"likes": 50})
    result = adaptive.vibe_fit(store, "short")
    assert "fit" in result
    tags = adaptive.adaptive_hashtags(store, "marketing")
    assert tags


# --------------------------------------------------------------------- feeds
RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test Blog</title>
  <item><title>Hello World Post</title><link>https://x/1</link>
    <description>An amazing intro to automation.</description></item>
  <item><title>Second Story</title><link>https://x/2</link>
    <description>More useful content here.</description></item>
</channel></rss>"""


def test_fetch_rss(fake_session):
    from tests.conftest import FakeResponse
    from socialbot.http import HttpClient
    from socialbot.feeds import fetch_rss

    fake_session.default = FakeResponse(status_code=200, text="",
                                        content=RSS_XML.encode())
    client = HttpClient(session=fake_session, retries=0)
    items = fetch_rss("https://example.com/feed.xml", http=client)
    assert len(items) == 2
    assert items[0]["title"] == "Hello World Post"


def test_run_feed_creates_drafts(store):
    from socialbot.feeds import run_feed
    store.save_account("mock", {})
    feed = FeedSource(name="blog", kind="curated",
                      items=[{"title": "Great content about growth",
                              "summary": "Growth tips", "link": "https://x/1"}])
    store.save_feed(feed)
    result = run_feed(feed, store)
    assert result["ok"] and result["drafts"] >= 1
    drafts = store.list_posts(status="draft")
    assert drafts and drafts[0].origin.startswith("feed:")


# -------------------------------------------------------------------- agents
def test_mention_monitor_live(store):
    store.save_account("mock", {})
    rule = MentionRule(name="watch", platform="mock", query="#python",
                       action="comment", limit_per_run=2, dry_run=False)
    store.save_monitor("mention", rule)
    results = AgentEngine(store).run_mentions(rule=rule.id)
    assert results[0]["ok"] and results[0]["acted"] == 2
    assert results[0]["dry_run"] is False
    # dedupe: second run sees nothing new
    again = AgentEngine(store).run_mentions(rule=rule.id)
    assert again[0]["acted"] == 0


def test_mention_blacklist_skips(store):
    store.save_account("mock", {})
    Safety(store).add("blacklist", "mock", "user1")
    rule = MentionRule(name="w", platform="mock", query="x", limit_per_run=5,
                       dry_run=False)
    store.save_monitor("mention", rule)
    result = AgentEngine(store).run_mentions(rule=rule.id)[0]
    assert result["acted"] < 5  # user1 skipped


def test_inbox_responder(store):
    store.save_account("mock", {})
    rule = InboxRule(name="inbox", platform="mock",
                     intents=["pricing", "demo", "thanks"],
                     escalate_webhook=None)
    store.save_inbox_rule(rule)
    result = AgentEngine(store).run_inbox(rule=rule.id)[0]
    assert result["ok"] and result["replied"] > 0


def test_competitor_watch(store):
    store.save_account("mock", {})
    watch = CompetitorRule(name="watch", platform="mock",
                           competitors=["rival"], interests="")
    store.save_monitor("competitor", watch)
    result = AgentEngine(store).run_competitors(rule=watch.id)[0]
    assert result["ok"]


def test_trend_capture(store):
    store.save_account("mock", {})
    reports = AgentEngine(store).run_trends(create_drafts=True)
    assert any(r["ok"] for r in reports)
    assert store.list_trends()
    assert store.list_posts(status="draft")  # drafts from trends


# ------------------------------------------------------------------ profiles
def test_profile_observe_and_similar(store):
    profiles_mod.observe(store, "mock", "alice", "I love python automation and bots")
    profiles_mod.observe(store, "mock", "bob", "cooking recipes today")
    similar = profiles_mod.find_similar(store, ["python", "automation"], platform="mock")
    assert [p.username for p in similar] == ["alice"]


# ---------------------------------------------------------------- publisher
def test_publish_variants(store):
    store.save_account("mock", {})
    post = Post(text="generic", platforms=["mock"],
                variants={"mock": "mock-specific text"})
    publisher = Publisher(store)
    result = publisher.publish_now(post)
    assert result.status == "published"
    assert result.results["mock"]["ok"]


def test_publish_thread(store):
    store.save_account("mock", {})
    post = Post(text=("sentence one. " * 400) + ("sentence two. " * 400),
                platforms=["mock"], thread=True)
    result = Publisher(store).publish_now(post)
    assert result.status == "published"
    res = result.results["mock"]
    assert res["ok"] and len(res.get("parts", [])) > 1


def test_schedule_clone_keeps_features(store):
    store.save_account("mock", {})
    post = Post(text="x", platforms=["mock"], thread=True, best_time=True,
                variants={"mock": "y"}, recurrence={"type": "interval", "value": 3600},
                status="published", scheduled_at=iso(utcnow()))
    store.save_post(post)
    clone = Publisher(store).schedule_next_occurrence(post)
    assert clone and clone.thread and clone.best_time and clone.variants == {"mock": "y"}


# ------------------------------------------------------------------ reports
def test_monthly_report(store):
    store.save_account("mock", {})
    post = Post(text="report test post", platforms=["mock"], status="published",
                published_at=iso(utcnow()),
                results={"mock": {"ok": True, "remote_id": "mock_1"}})
    store.save_post(post)
    store.save_metrics(post.id, "mock", "mock_1",
                       {"likes": 5, "comments": 1, "shares": 2, "impressions": 100})
    from socialbot.reports import monthly_report, render_report
    month = utcnow().strftime("%Y-%m")
    report = monthly_report(store, month)
    assert report["posts_published"] >= 1
    assert report["engagement"]["likes"] >= 5
    text = render_report(report)
    assert "growth report" in text


# ------------------------------------------------------------------- scheduler
def test_scheduler_jobs_registered(store, monkeypatch):
    monkeypatch.setenv("SOCIALBOT_AGENTS_INTERVAL", "15")
    monkeypatch.setenv("SOCIALBOT_FEEDS_INTERVAL", "30")
    scheduler = Scheduler(store, tick_seconds=60)
    scheduler.start()
    try:
        jobs = scheduler._scheduler.get_jobs()
        ids = {j.id for j in jobs}
        assert {"tick", "metrics", "agents", "feeds", "trends", "report"} <= ids
    finally:
        scheduler.stop()