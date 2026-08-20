"""Local OAuth flows — connect platforms the way you sign in with Google.

Two entry points share the same machinery:

- **API / dashboard**: ``POST /api/accounts/{platform}/oauth/start`` returns an
  authorization URL; the FastAPI app itself serves the redirect callback
  (``/api/accounts/{platform}/oauth/callback``), exchanges the code and stores
  the tokens — one-click connect from the Accounts page.
- **CLI**: ``socialbot connect <platform>`` runs a tiny local callback server,
  opens your browser, and saves the account when you authorize.

OAuth metadata lives on each platform class as ``Platform.oauth``::

    oauth = {
        "provider": "Google",                      # shown on the connect button
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/youtube.upload",
        "client_id_key": "client_id",
        "client_secret_key": "client_secret",
        "pkce": False,                             # optional PKCE (S256)
    }
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode

from .http import HttpClient
from .models import dumps
from .platforms import PlatformError, get_platform_class

log = logging.getLogger("socialbot.oauth")

PENDING_STATES: Dict[str, Dict[str, Any]] = {}   # state -> flow info (API mode)
STATE_TTL = 300                                   # seconds a pending flow stays valid
STATE_FILE = os.environ.get("SOCIALBOT_OAUTH_STATE_FILE") or "oauth_states.json"
_LOCK = threading.Lock()


def _persist_states() -> None:
    """Write pending states to disk so a dashboard restart can't orphan a flow."""
    try:
        with _LOCK:
            with open(STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(PENDING_STATES, fh)
    except OSError:
        log.warning("could not persist oauth states to %s", STATE_FILE)


def _load_states() -> None:
    try:
        with _LOCK:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                PENDING_STATES.update(json.load(fh))
    except (OSError, ValueError):
        pass


def store_pending_state(state: str, payload: Dict[str, Any]) -> None:
    """Remember a pending OAuth flow (in-memory + on disk)."""
    payload = dict(payload)
    payload.setdefault("expires", time.time() + STATE_TTL)
    with _LOCK:
        PENDING_STATES[state] = payload
    _persist_states()


def pop_pending_state(state: str) -> tuple:
    """Resolve a callback state.

    Returns ``(payload, None)`` on success, ``(None, reason)`` on failure where
    reason is ``"expired"`` (session older than the TTL) or ``"unknown"``.
    Survives dashboard restarts via the on-disk copy.
    """
    now = time.time()
    with _LOCK:
        payload = PENDING_STATES.pop(state, None)
    if payload is None:
        _load_states()
        with _LOCK:
            payload = PENDING_STATES.pop(state, None)
        if payload is None:
            return None, "unknown"
    if payload.get("expires", 0) < now:
        return None, "expired"
    return payload, None


# ------------------------------------------------------------------ helpers
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_pair() -> tuple:
    """Generate (code_verifier, code_challenge) for PKCE (S256)."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    """Decode the payload of a JWT (id_token) without verifying the signature."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def new_state() -> str:
    return secrets.token_urlsafe(24)


def build_auth_url(platform_name: str, client_id: str, redirect_uri: str,
                   state: str) -> tuple:
    """Return (authorization_url, code_verifier_or_None)."""
    meta = _oauth_meta(platform_name)
    if not client_id:
        raise PlatformError(f"{platform_name}: missing client id — set it first")
    params: Dict[str, Any] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": meta.get("scope", ""),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    verifier = None
    if meta.get("pkce"):
        verifier, challenge = pkce_pair()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return f"{meta['auth_url']}?{urlencode(params)}", verifier


def _oauth_meta(platform_name: str) -> Dict[str, Any]:
    cls = get_platform_class(platform_name)
    meta = cls.oauth
    if not meta:
        raise PlatformError(f"{platform_name} does not support one-click OAuth "
                            f"(connect it manually with `socialbot accounts add {platform_name}`)")
    return meta


# ------------------------------------------------------------------ exchange
def exchange_code(platform_name: str, client_id: str, client_secret: str, code: str,
                  redirect_uri: str, verifier: Optional[str] = None,
                  http: Optional[HttpClient] = None) -> Dict[str, Any]:
    """Exchange an authorization code for tokens. Returns config updates.

    Platforms that hand back a JWT id_token (LinkedIn) get their account id
    (``sub``) decoded automatically into ``member_id``.
    """
    meta = _oauth_meta(platform_name)
    client = http or HttpClient()
    data: Dict[str, Any] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if verifier:
        data["code_verifier"] = verifier
    resp = client.session.post(meta["token_url"], data=data, timeout=client.timeout)
    if not resp.ok:
        raise PlatformError(f"{platform_name} oauth exchange failed: "
                            f"HTTP {resp.status_code} {resp.text[:200]}")
    body = resp.json() if resp.content else {}
    if not body.get("access_token"):
        raise PlatformError(f"{platform_name} oauth exchange returned no access_token")

    updates: Dict[str, Any] = {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token"),
    }
    if "member_id" in meta.get("from_id_token", []):
        sub = decode_jwt_payload(body.get("id_token", "")).get("sub")
        if sub:
            updates["member_id"] = sub
    return {k: v for k, v in updates.items() if v is not None}


def refresh_token(platform_name: str, client_id: str, client_secret: str,
                  refresh: str, http: Optional[HttpClient] = None) -> Optional[str]:
    """Refresh an expired access token. Returns the new access token or None."""
    meta = _oauth_meta(platform_name)
    client = http or HttpClient()
    resp = client.session.post(
        meta["token_url"],
        data={"client_id": client_id, "client_secret": client_secret,
              "refresh_token": refresh, "grant_type": "refresh_token"},
        timeout=client.timeout)
    if resp.ok and resp.content:
        return resp.json().get("access_token")
    return None


# ------------------------------------------------------------------- CLI flow
def run_cli_flow(platform_name: str, store, config: Dict[str, Any],
                 port: int = 8765, timeout: float = 180.0) -> Dict[str, Any]:
    """Run the interactive browser flow: local callback server + exchange.

    Saves the resulting tokens into *store* and returns the saved account
    dict. Raises PlatformError if the user cancels or times out.
    """
    meta = _oauth_meta(platform_name)
    client_id = config.get(meta.get("client_id_key", "client_id"), "")
    client_secret = config.get(meta.get("client_secret_key", "client_secret"), "")
    if not client_id:
        raise PlatformError(f"{platform_name}: set your OAuth client id first "
                            f"(`socialbot accounts add {platform_name} --set {meta.get('client_id_key', 'client_id')}=...`)")

    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = new_state()
    auth_url, verifier = build_auth_url(platform_name, client_id, redirect_uri, state)

    result: Dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            params = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            if self.path.startswith("/callback") and params.get("state", [""])[0] == state:
                result["code"] = params.get("code", [""])[0]
                result["error"] = params.get("error", [""])[0]
                body = (b"<!doctype html><meta charset=utf-8><title>SocialBot</title>"
                        b"<body style='font-family:sans-serif;text-align:center;padding:80px'>"
                        b"<h2>&#9989; Authorized</h2><p>You can close this tab and return to the terminal.</p>")
            else:
                result["error"] = "unexpected request"
                body = b"<h2>Unexpected request</h2>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence the default stderr logging
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("opening browser for %s — redirect URI: %s", platform_name, redirect_uri)
    webbrowser.open(auth_url)

    deadline = time.time() + timeout
    try:
        while time.time() < deadline and not result:
            time.sleep(0.2)
    finally:
        server.shutdown()
        server.server_close()

    if result.get("error"):
        raise PlatformError(f"{platform_name} oauth cancelled or denied: {result['error']}")
    if not result.get("code"):
        raise PlatformError(f"{platform_name} oauth timed out after {timeout:.0f}s — try again")

    updates = exchange_code(platform_name, client_id, client_secret,
                            result["code"], redirect_uri, verifier)
    config.update(updates)
    account = store.save_account(platform_name, config)
    return account