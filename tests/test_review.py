"""Tests for the human-in-the-loop review queue (v1.4.0).

Agent-generated drafts (feeds, trends, competitors) are flagged
review_status="pending" and wait for approval/rejection via
CLI, API and dashboard before going live.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from socialbot.cli import cli
from socialbot.models import Post, PostStatus, iso, utcnow
from socialbot.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "review.db"))


@pytest.fixture
def client(tmp_path):
    from socialbot.api.app import create_app
    store = Store(str(tmp_path / "api_review.db"))
    store.save_account("mock", {}, label="demo")
    app = create_app(store=store, with_scheduler=False)
    with TestClient(app) as c:
        yield c, store


def pending_draft(store: Store, origin="feed:blog", text="hello world from the agent"):
    post = Post(text=text, platforms=[], status=PostStatus.DRAFT.value,
                origin=origin, review_status="pending")
    store.save_post(post)
    return post


# ------------------------------------------------------------ store layer
def test_agent_drafts_are_pending_by_default(store):
    post = Post(text="drafted by agent", platforms=[], status=PostStatus.DRAFT.value,
                origin="feed:rss", review_status="pending")
    store.save_post(post)
    fetched = store.get_post(post.id)
    assert fetched.review_status == "pending"

    queued = store.list_posts_for_review("pending")
    assert [p.id for p in queued] == [post.id]


def test_approve_then_list_filters(store):
    p = pending_draft(store)
    store.set_review(p.id, "approved")
    assert store.list_posts_for_review("pending") == []
    approved = store.list_posts_for_review("approved")
    assert [x.id for x in approved] == [p.id]
    assert approved[0].reviewed_at is not None


def test_reject_keeps_post_with_status(store):
    p = pending_draft(store)
    store.set_review(p.id, "rejected")
    post = store.get_post(p.id)
    assert post.review_status == "rejected"
    assert post.status == PostStatus.DRAFT.value


# ------------------------------------------------------------ agents write
def test_feed_drafts_are_pending(store):
    from socialbot.feeds import suggest_from_items
    drafts = suggest_from_items(
        [{"title": "The future of edge AI", "summary": "Why agents are taking over",
          "link": "https://x.dev/a", "source": "dev-news"}], n=1, platforms=["mock"])
    assert drafts
    assert drafts[0].review_status == "pending"
    assert drafts[0].origin.startswith("feed:")


def test_trend_drafts_are_pending(store):
    from socialbot.feeds import capture_trends
    store.save_account("mock", {}, label="demo")
    reports = capture_trends(store, create_drafts=True)
    assert reports
    pending = store.list_posts_for_review("pending")
    assert pending, "mock trending should produce pending drafts"
    assert all(p.review_status == "pending" for p in pending)
    assert all(p.origin.startswith("trend:") for p in pending)


# ------------------------------------------------------------ API
def test_api_review_list(client):
    c, store = client
    pending_draft(store, origin="feed:blog", text="needs a human")
    r = c.get("/api/review")
    assert r.status_code == 200
    data = r.json()
    assert data["stats"]["pending"] == 1
    assert data["pending"][0]["origin"] == "feed:blog"


def test_api_approve_with_platforms_and_schedule(client):
    c, store = client
    p = pending_draft(store)
    r = c.post(f"/api/review/{p.id}/approve",
               json={"platforms": ["mock"], "best_time": True})
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "approved"
    assert body["platforms"] == ["mock"]
    assert body["status"] == "scheduled"
    assert body["scheduled_at"]  # best-time computed


def test_api_approve_publish_now(client):
    from socialbot.models import parse_dt
    c, store = client
    p = pending_draft(store)
    r = c.post(f"/api/review/{p.id}/approve", json={"scheduled_at": "now"})
    assert r.status_code == 200
    assert r.json()["status"] == "scheduled"
    delta = abs((parse_dt(r.json()["scheduled_at"]) - utcnow()).total_seconds())
    assert delta < 60


def test_api_approve_stays_draft_without_schedule(client):
    c, store = client
    p = pending_draft(store)
    r = c.post(f"/api/review/{p.id}/approve", json={})
    assert r.status_code == 200
    assert r.json()["status"] == PostStatus.DRAFT.value


def test_api_reject(client):
    c, store = client
    p = pending_draft(store)
    r = c.post(f"/api/review/{p.id}/reject", json={"note": "spammy"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "rejected"
    assert store.get_post(p.id).review_status == "rejected"


def test_api_review_missing_post(client):
    c, _ = client
    assert c.post("/api/review/nope/approve", json={}).status_code == 404
    assert c.post("/api/review/nope/reject", json={}).status_code == 404


# ------------------------------------------------------------ CLI
@pytest.fixture
def runner(store, monkeypatch):
    monkeypatch.setattr("socialbot.cli.get_store", lambda: store)
    return CliRunner()


def test_cli_review_list_empty(runner):
    res = runner.invoke(cli, ["review", "list"])
    assert res.exit_code == 0
    assert "review queue is empty" in res.output


def test_cli_review_approve_schedules(runner, store):
    p = pending_draft(store, origin="trend:mock:ai")
    res = runner.invoke(cli, ["review", "approve", p.id,
                              "--platforms", "mock", "--at",
                              (utcnow() + timedelta(hours=2)).isoformat()])
    assert res.exit_code == 0, res.output
    post = store.get_post(p.id)
    assert post.review_status == "approved"
    assert post.platforms == ["mock"]
    assert post.status == PostStatus.SCHEDULED.value
    assert post.scheduled_at


def test_cli_review_approve_best_time(runner, store):
    p = pending_draft(store)
    res = runner.invoke(cli, ["review", "approve", p.id, "--best-time"])
    assert res.exit_code == 0, res.output
    assert store.get_post(p.id).status == PostStatus.SCHEDULED.value


def test_cli_review_reject(runner, store):
    p = pending_draft(store)
    res = runner.invoke(cli, ["review", "reject", p.id, "--note", "not on brand"])
    assert res.exit_code == 0, res.output
    post = store.get_post(p.id)
    assert post.review_status == "rejected"
    assert post.status == PostStatus.DRAFT.value


def test_cli_review_missing_post(runner):
    res = runner.invoke(cli, ["review", "approve", "nope"])
    assert res.exit_code != 0
    assert "not found" in res.output