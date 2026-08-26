"""Gemini / Google account sign-in (OAuth PKCE) for SocialBot.

Parallel to ChatGPT OAuth: browser Google sign-in, tokens in SQLite under
platform key "gemini", generation via Generative Language API with Bearer token.

Requires a Google Cloud OAuth Desktop client_id (free to create). Env:
  SOCIALBOT_GEMINI_CLIENT_ID
  SOCIALBOT_GEMINI_CLIENT_SECRET   (optional)

Operator owns the GCP OAuth client and signs in with their own Google account.
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
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode

import requests

logger = logging.getLogger("socialbot.gemini_oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

SCOPES = " ".join(
    [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/generative-language",
        "https://www.googleapis.com/auth/generative-language.retriever",
    ]
)
SAFETY_MARGIN = 60


def _pkce() -> tuple:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _client_id() -> str:
    cid = os.environ.get("SOCIALBOT_GEMINI_CLIENT_ID", "").strip()
    if not cid:
        raise RuntimeError(
            "Set SOCIALBOT_GEMINI_CLIENT_ID to your Google OAuth Desktop client ID. "
            "Create one free: Google Cloud Console → APIs & Services → Credentials → "
            "Create OAuth client → Desktop app. Enable Generative Language API."
        )
    return cid


def _client_secret() -> Optional[str]:
    return os.environ.get("SOCIALBOT_GEMINI_CLIENT_SECRET", "").strip() or None


class GeminiOAuth:
    """Google account OAuth for Gemini generateContent."""

    def __init__(self, store=None, tokens: Optional[Dict[str, Any]] = None):
        self.store = store
        self._tokens: Dict[str, Any] = dict(tokens or {})
        if not self._tokens and store is not None:
            acc = store.get_account("gemini")
            if acc and acc.get("config"):
                self._tokens = dict(acc["config"])

    def is_authenticated(self) -> bool:
        return bool(self._tokens.get("access_token"))

    def account_id(self) -> Optional[str]:
        return self._tokens.get("email") or self._tokens.get("account_id")

    def status(self) -> Dict[str, Any]:
        return {
            "authenticated": self.is_authenticated(),
            "email": self._tokens.get("email"),
            "account_id": self.account_id(),
            "expires": self._tokens.get("expires"),
            "has_refresh": bool(self._tokens.get("refresh_token")),
        }

    def _save(self) -> None:
        if self.store is None:
            return
        cfg = {
            "access_token": self._tokens.get("access_token"),
            "refresh_token": self._tokens.get("refresh_token"),
            "expires": self._tokens.get("expires"),
            "email": self._tokens.get("email"),
            "id_token": self._tokens.get("id_token"),
            "token_type": self._tokens.get("token_type") or "Bearer",
        }
        self.store.save_account("gemini", cfg, label="Gemini / Google account")
        self.store.log_event("gemini.auth", "Gemini tokens saved")

    def _set_from_response(self, tokens: dict) -> None:
        expires_in = int(tokens.get("expires_in") or 3600)
        expires_ms = int(time.time() * 1000) + expires_in * 1000
        email = self._tokens.get("email")
        id_token = tokens.get("id_token")
        if id_token:
            try:
                payload_b64 = id_token.split(".")[1]
                payload_b64 += "=" * (-len(payload_b64) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                email = payload.get("email") or email
            except Exception:
                pass
        self._tokens = {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token") or self._tokens.get("refresh_token"),
            "id_token": id_token,
            "expires": expires_ms,
            "email": email,
            "token_type": tokens.get("token_type") or "Bearer",
        }
        self._save()

    def refresh_if_needed(self) -> bool:
        if not self.is_authenticated():
            return False
        expires = self._tokens.get("expires") or 0
        now_ms = int(time.time() * 1000)
        if expires and now_ms < (expires - SAFETY_MARGIN * 1000):
            return True
        refresh = self._tokens.get("refresh_token")
        if not refresh:
            return False
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": _client_id(),
        }
        secret = _client_secret()
        if secret:
            data["client_secret"] = secret
        try:
            resp = requests.post(TOKEN_URL, data=data, timeout=30)
            if 200 <= resp.status_code < 300:
                self._set_from_response(resp.json())
                return True
            logger.warning("gemini refresh failed: %s %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("gemini refresh error: %s", e)
        return False

    def access_token(self) -> Optional[str]:
        if not self.refresh_if_needed():
            return None
        return self._tokens.get("access_token")

    def login(self, open_browser: bool = True, timeout: float = 180.0, port: int = 8766) -> Dict[str, Any]:
        client_id = _client_id()
        verifier, challenge = _pkce()
        redirect_uri = f"http://127.0.0.1:{port}/callback"
        result: Dict[str, Any] = {"code": None, "error": None, "done": threading.Event()}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                qs = parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
                if "code" in qs:
                    result["code"] = qs["code"][0]
                    body = b"<html><body><h2>Gemini linked. You can close this tab.</h2></body></html>"
                    self.send_response(200)
                else:
                    result["error"] = qs.get("error", ["unknown"])[0]
                    body = b"<html><body><h2>Auth failed. Close tab and retry.</h2></body></html>"
                    self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                result["done"].set()
                threading.Thread(target=server.shutdown, daemon=True).start()

        server = HTTPServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{AUTH_URL}?{urlencode(params)}"
        if open_browser:
            webbrowser.open(auth_url)
        else:
            print(f"Open this URL to sign in:\n{auth_url}\n")

        if not result["done"].wait(timeout=timeout):
            server.shutdown()
            raise TimeoutError("Gemini sign-in timed out")
        if result["error"] or not result["code"]:
            raise RuntimeError(result["error"] or "no auth code")

        data = {
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        }
        secret = _client_secret()
        if secret:
            data["client_secret"] = secret
        token_resp = requests.post(TOKEN_URL, data=data, timeout=30)
        if not (200 <= token_resp.status_code < 300):
            raise RuntimeError(
                f"token exchange failed: {token_resp.status_code} {token_resp.text[:400]}"
            )
        self._set_from_response(token_resp.json())
        return self.status()

    def logout(self) -> None:
        token = self._tokens.get("access_token")
        if token:
            try:
                requests.post(REVOKE_URL, data={"token": token}, timeout=15)
            except Exception:
                pass
        self._tokens = {}
        if self.store is not None:
            try:
                self.store.delete_account("gemini")
            except Exception:
                self.store.save_account("gemini", {}, label="Gemini / Google account")
            self.store.log_event("gemini.logout", "Gemini tokens cleared")

    def generate(self, prompt: str, model: str = "gemini-2.0-flash", n: int = 1) -> List[str]:
        token = self.access_token()
        if not token:
            raise RuntimeError("not signed in — run: socialbot gemini login")
        url = GEMINI_GENERATE_URL.format(model=model)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"candidateCount": max(1, min(n, 4))},
        }
        r = requests.post(url, headers=headers, json=payload, timeout=90)
        if r.status_code != 200:
            raise RuntimeError(
                f"Gemini generate failed: {r.status_code} {r.text[:300]}. "
                "Enable Generative Language API on the GCP project that owns the OAuth client."
            )
        data = r.json()
        texts: List[str] = []
        for cand in data.get("candidates") or []:
            parts = (cand.get("content") or {}).get("parts") or []
            chunk = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            if chunk:
                texts.append(chunk)
        if not texts:
            raise RuntimeError("Gemini returned empty candidates")
        return texts[:n] if n > 1 else [texts[0]]
