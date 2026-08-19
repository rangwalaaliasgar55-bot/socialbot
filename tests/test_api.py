"""API tests via FastAPI TestClient."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from socialbot.api.app import create_app  # noqa: E402
from socialbot.storage import Store  # noqa: E402


@pytest.fixture
def client(tmp_path):
    store = Store(str(tmp_path / "api.db"))
    store.save_account("mock", {}, label="demo")
    app = create_app(store=store, with_scheduler=False)
    os.environ["SOCIALBOT_NO_AUTO_APP"] = "1"
    with TestClient(app) as c:
        yield c, store


def test_health(client):
    c, _ = client
    body = c.get("/api/health").json()
    assert body["ok"] is True
    assert "scheduler" in body


def test_platforms_endpoint(client):
    c, _ = client
    platforms = c.get("/api/platforms").json()
    names = {p["name"] for p in platforms}
    assert "mock" in names and "mastodon" in names
    mock = next(p for p in platforms if p["name"] == "mock")
    assert mock["configured"] is True


def test_create_post_publish_now(client):
    c, store = client
    resp = c.post("/api/posts", json={"text": "hello api", "platforms": ["mock"],
                                      "publish_now": True})
    assert resp.status_code == 201
    post = resp.json()
    assert post["status"] == "published"
    assert post["results"]["mock"]["ok"] is True
    assert store.get_post(post["id"]) is not None


def test_create_post_schedule(client):
    c, _ = client
    resp = c.post("/api/posts", json={"text": "later", "platforms": ["mock"],
                                      "scheduled_at": "2030-01-01T09:00:00Z"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "scheduled"

    # list, cancel, delete
    assert len(c.get("/api/posts", params={"status": "scheduled"}).json()) == 1
    post_id = resp.json()["id"]
    assert c.delete(f"/api/posts/{post_id}").json()["status"] == "cancelled"
    assert c.delete(f"/api/posts/{post_id}").json()["ok"] is True


def test_create_post_validation(client):
    c, _ = client
    assert c.post("/api/posts", json={"text": "x", "platforms": []}).status_code == 422
    resp = c.post("/api/posts", json={"text": "x", "platforms": ["myspace"]})
    assert resp.status_code == 422


def test_publish_and_retry(client):
    c, _ = client
    post = c.post("/api/posts", json={"text": "x", "platforms": ["mock"],
                                      "scheduled_at": "2030-01-01T00:00:00Z"}).json()
    resp = c.post(f"/api/posts/{post['id']}/publish")
    assert resp.json()["status"] == "published"
    assert c.post(f"/api/posts/{post['id']}/retry").json()["status"] == "published"


def test_scheduler_control(client):
    c, store = client
    c.post("/api/scheduler/tick")
    body = c.get("/api/health").json()
    assert body["scheduler"]["running"] is False  # disabled in tests


def test_accounts_upsert_masks_secrets(client):
    c, store = client
    resp = c.post("/api/accounts", json={
        "platform": "mastodon",
        "label": "main",
        "config": {"instance": "https://m.social", "access_token": "secret-token"}})
    assert resp.status_code == 201
    body = resp.json()
    assert body["verified"] in (True, False)  # verify attempted (network may fail)

    listed = c.get("/api/accounts").json()
    account = next(a for a in listed if a["platform"] == "mastodon")
    assert account["config"]["access_token"] == "•••"
    assert account["config"]["instance"] == "https://m.social"

    # partial update must not wipe the masked secret
    c.post("/api/accounts", json={"platform": "mastodon",
                                  "config": {"instance": "https://other.social",
                                             "access_token": "•••"}})
    stored = store.get_account("mastodon")
    assert stored["config"]["access_token"] == "secret-token"
    assert stored["config"]["instance"] == "https://other.social"

    assert c.delete("/api/accounts/mastodon").json()["ok"] is True


def test_bot_rules_crud_and_run(client):
    c, _ = client
    rule = c.post("/api/bot/rules", json={
        "name": "like python", "platform": "mock", "action": "like",
        "trigger_type": "hashtag", "trigger_value": "python", "dry_run": True}).json()
    assert rule["id"]

    run = c.post(f"/api/bot/rules/{rule['id']}/run").json()
    assert run["ok"] is True and run["acted"] > 0

    all_runs = c.post("/api/bot/run").json()
    assert all_runs["results"]
    assert c.delete(f"/api/bot/rules/{rule['id']}").json()["ok"] is True


def test_analytics_endpoints(client):
    c, _ = client
    c.post("/api/posts", json={"text": "metrics!", "platforms": ["mock"], "publish_now": True})
    c.post("/api/analytics/refresh")
    summary_body = c.get("/api/analytics/summary").json()
    assert summary_body["total_posts"] == 1
    assert summary_body["by_status"]["published"] == 1

    csv_resp = c.get("/api/analytics/export.csv")
    assert csv_resp.status_code == 200
    assert "post_id" in csv_resp.text


def test_generate_endpoint(client):
    c, _ = client
    body = c.post("/api/generate", json={"topic": "python automation", "n": 2}).json()
    assert len(body["drafts"]) == 2
    assert all("text" in d for d in body["drafts"])


def test_events_logged(client):
    c, _ = client
    c.post("/api/posts", json={"text": "logged", "platforms": ["mock"], "publish_now": True})
    events = c.get("/api/events").json()
    assert any(e["type"] == "publish.ok" for e in events)


def test_dashboard_served(client):
    c, _ = client
    index = c.get("/")
    assert index.status_code == 200
    assert "SocialBot" in index.text
