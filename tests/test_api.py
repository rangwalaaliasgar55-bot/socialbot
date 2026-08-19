"""API tests via FastAPI TestClient."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["SOCIALBOT_NO_AUTO_APP"] = "1"

from socialbot.api.app import create_app  # noqa: E402
from socialbot.storage import Store  # noqa: E402


@pytest.fixture
def client(tmp_path):
    store = Store(str(tmp_path / "api.db"))
    store.save_account("mock", {}, label="demo")
    app = create_app(store=store, with_scheduler=False)
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
