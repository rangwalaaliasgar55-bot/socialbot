"""Thin HTTP layer with retries, timeouts and an injectable transport for tests."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests


class HttpError(Exception):
    """Raised on non-2xx responses. Carries parsed body when possible."""

    def __init__(self, status: int, message: str, body: Any = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.body = body

    @property
    def rate_limited(self) -> bool:
        return self.status in (429, 503)


class HttpClient:
    """Small wrapper around requests.Session with retry/backoff.

    Tests substitute the session to avoid real network traffic.
    """

    def __init__(self, session: Optional[requests.Session] = None,
                 timeout: float = 20.0, retries: int = 2, backoff: float = 1.5):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    def request(self, method: str, url: str, *,
                params: Optional[Dict[str, Any]] = None,
                json: Any = None,
                data: Any = None,
                headers: Optional[Dict[str, str]] = None,
                files: Any = None) -> requests.Response:
        attempt = 0
        while True:
            try:
                resp = self.session.request(
                    method, url, params=params, json=json, data=data,
                    headers=headers, files=files, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.retries:
                    raise HttpError(0, f"network error: {exc}") from exc
                attempt += 1
                time.sleep(self.backoff ** attempt * 0.3)
                continue

            if resp.status_code >= 400 and self._should_retry(resp.status_code) and attempt < self.retries:
                attempt += 1
                time.sleep(self.backoff ** attempt * 0.3)
                continue
            return resp

    @staticmethod
    def _should_retry(status: int) -> bool:
        return status in (429, 500, 502, 503, 504)

    # Convenience helpers returning parsed JSON ---------------------------
    def get_json(self, url: str, **kw) -> Any:
        return self._parse(self.request("GET", url, **kw))

    def post_json(self, url: str, **kw) -> Any:
        return self._parse(self.request("POST", url, **kw))

    def put_json(self, url: str, **kw) -> Any:
        return self._parse(self.request("PUT", url, **kw))

    def delete_json(self, url: str, **kw) -> Any:
        return self._parse(self.request("DELETE", url, **kw))

    @staticmethod
    def _parse(resp: requests.Response) -> Any:
        if resp.status_code >= 400:
            message = resp.text[:500] if resp.text else resp.reason
            body = None
            try:
                body = resp.json()
            except ValueError:
                pass
            raise HttpError(resp.status_code, message, body)
        try:
            return resp.json()
        except ValueError:
            return resp.text
