"""OAuth connect flow tests — URL building, token exchange, API wiring (offline)."""
import base64
import json

import pytest

from socialbot.http import HttpClient
from socialbot.oauth import (build_auth_url, decode_jwt_payload, exchange_code,
                             new_state, pkce_pair, refresh_token)
from socialbot.platforms import PlatformError
from socialbot.storage import Store

from conftest import FakeResponse, FakeSession


def _jwt(payload: dict) -> str:
    enc = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'none'})}.{enc(payload)}.sig"


def _http(session) -> HttpClient:
    return HttpClient(session=session, retries=0)


# ------------------------------------------------------------------ helpers
def test_pkce_pair():
    verifier, challenge = pkce_pair()
    assert verifier and challenge
    assert verifier != challenge


def test_decode_jwt_payload():
    assert decode_jwt_payload(_jwt({"sub": "abc123", "name": "Ali"})) == {
        "sub": "abc123", "name": "Ali"}
    assert decode_jwt_payload("garbage") == {}


def test_new_state_unique():
    assert new_state() != new_state()


# -------------------------------------------------------------- auth URL
def test_build_auth_url_standard():
    url, verifier = build_auth_url("linkedin", "cid123", "http://localhost:8000/cb", "st1")
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "client_id=cid123" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcb" in url
    assert "response_type=code" in url
    assert "scope=openid+profile+w_member_social" in url
    assert "state=st1" in url
    assert verifier is None  # no PKCE


def test_build_auth_url_pkce():
    url, verifier = build_auth_url("twitter", "cid", "http://127.0.0.1:8765/callback", "st2")
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert verifier is not None


def test_build_auth_url_requires_client_id():
    with pytest.raises(PlatformError, match="client id"):
        build_auth_url("linkedin", "", "http://x/cb", "st")


def test_unknown_platform_no_oauth():
    with pytest.raises(PlatformError, match="does not support one-click OAuth"):
        build_auth_url("telegram", "x", "http://x/cb", "st")


# ------------------------------------------------------------- exchange
def test_exchange_code_saves_tokens():
    session = FakeSession(routes={
        ("POST", "https://oauth2.googleapis.com/token"): FakeResponse(
            200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})})
    updates = exchange_code("youtube", "cid", "sec", "CODE", "http://localhost:8000/cb",
                            "verifier", http=_http(session))
    assert updates == {"access_token": "AT", "refresh_token": "RT"}
    call = session.last("POST", "oauth2.googleapis.com")
    assert call["data"]["grant_type"] == "authorization_code"
    assert call["data"]["code"] == "CODE"
    assert call["data"]["code_verifier"] == "verifier"


def test_exchange_linkedin_reads_member_id_from_id_token():
    session = FakeSession(routes={
        ("POST", "https://www.linkedin.com/oauth/v2/accessToken"): FakeResponse(
            200, {"access_token": "AT", "id_token": _jwt({"sub": "4t6Fv8rXkQ"})})})
    updates = exchange_code("linkedin", "cid", "sec", "C", "http://localhost:8000/cb",
                            http=_http(session))
    assert updates["access_token"] == "AT"
    assert updates["member_id"] == "4t6Fv8rXkQ"


def test_exchange_failure_raises():
    session = FakeSession(default=FakeResponse(400, {"error": "invalid_grant"}))
    with pytest.raises(PlatformError, match="oauth exchange failed"):
        exchange_code("youtube", "cid", "sec", "BAD", "http://x/cb", http=_http(session))


def test_refresh_token():
    session = FakeSession(routes={
        ("POST", "https://oauth2.googleapis.com/token"): FakeResponse(
            200, {"access_token": "NEW"})})
    got = refresh_token("youtube", "cid", "sec", "RT", http=_http(session))
    assert got == "NEW"
    assert session.last("POST", "oauth2.googleapis.com")["data"]["grant_type"] == "refresh_token"


# -------------------------------------------------------------- API wiring
@pytest.fixture
def oauth_client(tmp_path, monkeypatch):
    import importlib
    from socialbot.api.app import create_app
    app_mod = importlib.import_module("socialbot.api.app")
    store = Store(str(tmp_path / "oauth.db"))
    app = create_app(store=store, with_scheduler=False)
    monkeypatch.setattr(app_mod, "exchange_code",
                        lambda *a, **k: {"access_token": "AT", "refresh_token": "RT"})
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c, store


def test_api_oauth_start_and_callback(oauth_client):
    c, store = oauth_client
    start = c.post("/api/accounts/youtube/oauth/start",
                   json={"client_id": "cid", "client_secret": "sec"}).json()
    assert "auth_url" in start and start["auth_url"].startswith("https://accounts.google.com/")
    assert start["redirect_uri"].endswith("/api/accounts/youtube/oauth/callback")
    assert "state=" in start["auth_url"]

    resp = c.get(f"/api/accounts/youtube/oauth/callback?code=CODE&state={start['state']}")
    assert resp.status_code == 200
    assert "Connected" in resp.text

    account = store.get_account("youtube")
    assert account["config"]["access_token"] == "AT"
    assert account["config"]["refresh_token"] == "RT"
    assert account["config"]["client_id"] == "cid"


def test_api_oauth_rejects_non_oauth_platform(oauth_client):
    c, _ = oauth_client
    assert c.post("/api/accounts/telegram/oauth/start",
                  json={"client_id": "x"}).status_code == 400


def test_api_oauth_unknown_state(oauth_client):
    c, _ = oauth_client
    resp = c.get("/api/accounts/youtube/oauth/callback?code=CODE&state=bogus")
    assert resp.status_code == 200
    assert "Authorization failed" in resp.text