"""Tests for the PR #3 ports: coordination layer, monitoring, AI content engine
and the real-time trend analyzer — all reconciled with the v1.2.0 agent engine."""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from socialbot.ai_engine import AIEngine, ContentStrategy, generate_content_package
from socialbot.coordination import AgentCoordinator, distributed_lock, get_coordinator
from socialbot.monitoring import (HealthChecker, HealthStatus, MetricsCollector,
                                  MonitoringSystem, OperationTracker)
from socialbot.storage import Store
from socialbot.trend_analyzer import RealTrendAnalyzer, TrendData


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "pr3.db"))


@pytest.fixture
def client(tmp_path):
    from socialbot.api.app import create_app
    store = Store(str(tmp_path / "api_pr3.db"))
    store.save_account("mock", {}, label="demo")
    app = create_app(store=store, with_scheduler=False)
    with TestClient(app) as c:
        yield c, store


# ------------------------------------------------------------- coordination
def test_task_lifecycle(store):
    coord = AgentCoordinator(store=store)
    task_id = coord.enqueue_task("publish", {"platform": "mock", "text": "hi"},
                                 priority=5, max_retries=2)
    task = coord.get_task(task_id)
    assert task.task_type == "publish"
    assert task.payload == {"platform": "mock", "text": "hi"}
    assert task.status == "pending"

    claimed = coord.claim_task(["publish"])
    assert claimed is not None and claimed.task_id == task_id
    assert claimed.status == "claimed"
    assert claimed.claimed_by == coord.agent_id

    coord.complete_task(task_id, {"ok": True})
    done = coord.get_task(task_id)
    assert done.status == "completed"
    assert done.result == {"ok": True}

    stats = coord.get_stats()
    assert stats["completed_today"] == 1
    assert stats["pending_tasks"] == 0
    coord.shutdown()


def test_task_retry_then_fail(store):
    coord = AgentCoordinator(store=store)
    task_id = coord.enqueue_task("bot_run", {}, max_retries=1)
    assert coord.claim_task(["bot_run"]) is not None
    coord.fail_task(task_id, "boom")
    task = coord.get_task(task_id)
    assert task.status == "pending"          # requeued for retry
    assert task.retry_count == 1
    assert coord.claim_task(["bot_run"]) is not None
    coord.fail_task(task_id, "boom again")
    task = coord.get_task(task_id)
    assert task.status == "failed"
    assert task.retry_count == 1
    stats = coord.get_stats()
    assert stats["failed_today"] == 1
    coord.shutdown()


def test_distributed_lock(store):
    coord = AgentCoordinator(store=store)
    with coord.acquire_lock("publish", timeout=5):
        assert coord.get_task  # lock held
    # a second coordinator (simulated other worker) can take it after release
    coord2 = AgentCoordinator(store=store)
    with coord2.acquire_lock("publish", timeout=5):
        pass
    # contention: hold the lock, other worker must fail fast
    coord3 = AgentCoordinator(store=store)
    holder = coord3.acquire_lock("publish", timeout=2)
    holder.__enter__()
    try:
        with pytest.raises(RuntimeError):
            with coord.acquire_lock("publish", timeout=1):
                pass
    finally:
        holder.__exit__(None, None, None)
    coord.shutdown()
    coord2.shutdown()
    coord3.shutdown()


def test_dead_agent_cleanup(store):
    coord = AgentCoordinator(store=store)
    task_id = coord.enqueue_task("publish", {})
    coord.claim_task(["publish"])
    # fake an expired heartbeat for our own agent row
    coord._get_conn().execute(
        "UPDATE agents SET last_heartbeat=? WHERE agent_id=?",
        ("2000-01-01T00:00:00+00:00", coord.agent_id))
    coord._get_conn().commit()
    dead = coord.cleanup_dead_agents()
    assert coord.agent_id in dead
    task = coord.get_task(task_id)
    assert task.status == "pending"  # released back to the queue
    assert task.claimed_by is None
    coord.shutdown()


def test_distributed_lock_helper(store):
    with distributed_lock("my-lock", timeout=5, store=store):
        assert True


# --------------------------------------------------------------- monitoring
def test_metrics_collector():
    m = MetricsCollector()
    m.increment("runs")
    m.increment("runs", 2)
    m.gauge("queue", 12.5)
    m.timing("op.duration", 40.0)
    assert m.get_counter("runs") == 3
    assert m.get_gauge("queue") == 12.5
    assert len(m.get_metric("runs.counter")) == 2
    assert len(m.get_metric("op.duration.timing")) == 1
    data = m.get_all_metrics()
    assert data["counters"]["runs"] == 3


def test_health_checks():
    hc = HealthChecker()
    hc.register_check("ok", lambda: HealthStatus(component="ok", status="healthy",
                                                 message="fine"))
    hc.register_check("bad", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    results = hc.run_checks()
    assert results["ok"].status == "healthy"
    assert results["bad"].status == "unhealthy"
    assert hc.get_overall_status() == "unhealthy"


def test_operation_tracker_success_and_failure():
    mon = MonitoringSystem()
    with mon.track_operation("agents.run"):
        time.sleep(0.01)
    assert mon.metrics.get_counter("agents.run.success") == 1
    with pytest.raises(ValueError):
        with mon.track_operation("agents.run"):
            raise ValueError("nope")
    assert mon.metrics.get_counter("agents.run.failure") == 1
    assert mon.metrics.get_counter("agents.run.started") == 2


def test_monitoring_full_status():
    mon = MonitoringSystem()
    status = mon.get_full_status()
    assert "health" in status and "metrics" in status and "resources" in status
    assert status["health"]["overall_status"] in ("healthy", "degraded", "unhealthy")


# ----------------------------------------------------------------- ai engine
def test_ai_engine_mock_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = AIEngine()
    assert engine.client is None  # offline mock mode

    strategy = ContentStrategy(topic="Remote Work", platform="linkedin",
                               tone="professional", target_audience="devs",
                               trending_keywords=["wfh", "coding"])
    prompt = engine.generate_smart_prompt(strategy)
    assert "Remote Work" in prompt
    assert engine.generate_image(prompt) is None
    seo = engine.generate_caption_and_seo(strategy, prompt)
    assert seo["caption"] and seo["hashtags"]
    assert seo["seo_score"] == 0.5


def test_ai_engine_full_package():
    package = generate_content_package("Sustainable Living", platform="instagram",
                                       tone="fun", target_audience="gen z")
    assert package.prompt
    assert package.caption
    assert package.hashtags
    assert package.platform_optimized
    assert package.to_dict()["seo_score"] >= 0


def test_ai_engine_platform_limits():
    engine = AIEngine()
    assert engine.platform_limits["twitter"]["chars"] == 280
    assert engine.platform_limits["linkedin"]["hashtags"] == 5


# ------------------------------------------------------------ trend analyzer
def test_trend_analyzer_mock_fallback(monkeypatch):
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    analyzer = RealTrendAnalyzer()
    trends = analyzer.get_trending_topics()
    assert len(trends) == 3  # demo trends
    assert all(isinstance(t, TrendData) for t in trends)
    assert trends[0].sentiment in ("positive", "neutral", "negative")
    # ranked by volume*growth
    assert trends[0].volume >= trends[-1].volume


def test_trend_analyzer_sentiment_via_nlp():
    from socialbot import intelligence as nlp
    analyzer = RealTrendAnalyzer()
    trend = analyzer.get_trending_topics()[0]
    assert trend.sentiment in ("positive", "neutral", "negative")
    assert nlp.sentiment_label(nlp.sentiment("I love this!")) == "positive"


def test_trend_strategy_for_platform():
    analyzer = RealTrendAnalyzer()
    strategy = analyzer.generate_content_strategy("linkedin")
    assert strategy["recommended_topic"]
    assert strategy["tone"] == "professional"
    assert strategy["optimal_posting_time"]


def test_trend_capture_writes_store(store, monkeypatch):
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    analyzer = RealTrendAnalyzer()
    reports = analyzer.capture(store, create_drafts=True)
    assert reports[0]["captured"] == 3
    assert len(store.list_trends()) == 3
    assert len(store.list_posts(status="draft")) == 3
    # second run dedupes
    reports2 = analyzer.capture(store, create_drafts=True)
    assert reports2[0]["captured"] == 0
    assert len(store.list_trends()) == 3


def test_run_trends_includes_real(store, monkeypatch):
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    from socialbot.agents import AgentEngine
    from socialbot.http import HttpClient
    reports = AgentEngine(store, HttpClient()).run_trends(create_drafts=False)
    platforms = {r["platform"] for r in reports}
    assert "trend-analyzer" in platforms


# --------------------------------------------------------------- API wiring
def test_api_monitoring_and_tasks(client):
    c, _ = client
    mon = c.get("/api/monitoring").json()
    assert "health" in mon and "metrics" in mon

    created = c.post("/api/tasks", json={"task_type": "publish",
                                         "payload": {"text": "x"},
                                         "priority": 3}).json()
    task_id = created["task_id"]
    task = c.get(f"/api/tasks/{task_id}").json()
    assert task["task_type"] == "publish"
    assert task["payload"] == {"text": "x"}
    assert c.get("/api/tasks").json()["tasks"][0]["task_id"] == task_id

    workers = c.get("/api/agents").json()
    assert "stats" in workers and "agents" in workers


def test_api_trend_strategy(client):
    c, _ = client
    strategy = c.post("/api/trends/strategy", params={"platform": "instagram"}).json()
    assert strategy["recommended_topic"]


def test_api_ai_content_mock(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c, _ = client
    body = c.post("/api/ai/content", json={
        "topic": "Coffee", "platform": "instagram", "tone": "fun",
        "target_audience": "students",
        "trending_keywords": ["latte", "morning"]}).json()
    assert body["caption"]
    assert body["hashtags"]
    assert body["image_url"] is None  # offline mock mode