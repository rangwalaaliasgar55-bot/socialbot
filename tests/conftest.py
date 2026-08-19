"""Shared test fixtures: temp store, fake HTTP session, test API client."""
from __future__ import annotations

import os

from unittest.mock import MagicMock

import pytest

# keep imports/background work out of the repo dir & off the test run
os.environ.setdefault("SOCIALBOT_DB", ":memory:")
os.environ.setdefault("SOCIALBOT_DISABLE_SCHEDULER", "1")

from socialbot.http import HttpClient  # noqa: E402
from socialbot.storage import Store  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", content=b""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or (str(json_data) if json_data is not None else "")
        self.content = content or (self.text.encode() or b"{}")
        self.reason = "OK" if status_code < 400 else "Error"

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._json


class FakeSession:
    """Records requests; returns canned responses per (method, url-substring)."""

    def __init__(self, routes=None, default=None):
        self.routes = routes or {}   # (METHOD, "url-part") -> FakeResponse | callable
        self.default = default or FakeResponse()
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        for (m, frag), resp in self.routes.items():
            if m == method and frag in url:
                return resp(self.calls[-1]) if callable(resp) else resp
        return self.default

    # shortcuts used by platforms
    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    def last(self, method=None, frag=None):
        hits = [c for c in self.calls
                if (method is None or c["method"] == method)
                and (frag is None or frag in c["url"])]
        return hits[-1] if hits else None


def fake_http(routes=None, default=None) -> HttpClient:
    return HttpClient(session=FakeSession(routes, default), retries=0)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


@pytest.fixture
def fake_session():
    return FakeSession()
