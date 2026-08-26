"""ChatGPT account sign-in (no API key) for SocialBot.

Uses the same OAuth PKCE flow as Codex / Stonic Gen 2 Option A:
sign in with your ChatGPT account → tokens stored locally → AI drafts
run against chatgpt.com/backend-api using your plan limits.

No OPENAI_API_KEY required. Tokens live in the SocialBot SQLite store
under platform key "chatgpt".
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

logger = logging.getLogger("socialbot.chatgpt_oauth")

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"

# Public client_id used by Codex CLI (same as Stonic / OpenCode style flows)
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
SCOPE = "openid profile email offline_access"
SAFETY_MARGIN = 60  # seconds before expiry to refresh


def extract_account_id(id_token: Optional[str], access_token: Optional[str]) -> Optional[str]:
    for token in (id_token, access_token):
        if not token:
            continue
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        except Exception:
            continue
        if aid := payload.get("chatgpt_account_id"):
            return aid
        if aid := payload.get("https://api.openai.com/auth", {}).get("chatgpt_account_id"):
            return aid
        orgs = payload.get("organizations") or []
        if orgs and (aid := orgs[0].get("id")):
            return aid
    return None


def _pkce() -> tuple:
    verifier = secrets.token_urlsafe(96)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class ChatGPTOAuth:
    """Manage ChatGPT OAuth tokens and call models via subscription."""

    def __init__(self, store=None, tokens: Optional[Dict[str, Any]] = None):
        self.store = store
        self._tokens: Dict[str, Any] = dict(tokens or {})
        if not self._tokens and store is not None:
            acc = store.get_account("chatgpt")
            if acc and acc.get("config"):
                self._tokens = dict(acc["config"])

    def is_authenticated(self) -> bool:
        return bool(self._tokens.get("access_token") or self._tokens.get("access"))

    def status(self) -> Dict[str, Any]:
        ok = self.is_authenticated()
        expires = self._tokens.get("expires") or self._tokens.get("expires_at")
        return {
            "authenticated": ok,
            "account_id": self._tokens.get("account_id") or self._tokens.get("accountId"),
            "expires": expires,
            "has_refresh": bool(self._tokens.get("refresh_token") or self._tokens.get("refresh")),
        }

    def _save(self) -> None:
        if self.store is None:
            return
        cfg = {
            "access_token": self._tokens.get("access_token") or self._tokens.get("access"),
            "refresh_token": self._tokens.get("refresh_token") or self._tokens.get("refresh"),
            "account_id": self._tokens.get("account_id") or self._tokens.get("accountId"),
            "expires": self._tokens.get("expires") or self._tokens.get("expires_at"),
            "id_token": self._tokens.get("id_token"),
        }
        self.store.save_account("chatgpt", cfg, label="ChatGPT account")
        self.store.log_event("chatgpt.auth", "ChatGPT tokens saved")

    def _set_from_response(self, tokens: dict, fallback_account_id: Optional[str] = None) -> None:
        expires_in = tokens.get("expires_in") or 3600
        expires_ms = int(time.time() * 1000) + int(expires_in) * 1000
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        id_token = tokens.get("id_token")
        account_id = extract_account_id(id_token, access) or fallback_account_id
        self._tokens = {
            "access_token": access,
            "refresh_token": refresh,
            "id_token": id_token,
            "account_id": account_id,
            "expires": expires_ms,
        }
        self._save()

    def refresh_if_needed(self) -> bool:
        if not self.is_authenticated():
            return False
        expires = self._tokens.get("expires") or 0
        now_ms = int(time.time() * 1000)
        if expires and now_ms < (expires - SAFETY_MARGIN * 1000):
            return True
        refresh = self._tokens.get("refresh_token") or self._tokens.get("refresh")
        if not refresh:
            return False
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": CLIENT_ID,
                },
                timeout=30,
            )
            if not (200 <= resp.status_code < 300):
                logger.error("token refresh failed: %s %s", resp.status_code, resp.text[:200])
                return False
            self._set_from_response(resp.json(), self._tokens.get("account_id"))
            return True
        except Exception as e:
            logger.error("token refresh error: %s", e)
            return False

    def access_token(self) -> Optional[str]:
        self.refresh_if_needed()
        return self._tokens.get("access_token") or self._tokens.get("access")

    def account_id(self) -> Optional[str]:
        return self._tokens.get("account_id") or self._tokens.get("accountId")

    def logout(self) -> None:
        self._tokens = {}
        if self.store is not None:
            self.store.delete_account("chatgpt")
            self.store.log_event("chatgpt.logout", "ChatGPT signed out")

    def login(self, port: int = 1455, open_browser: bool = True, timeout: int = 300) -> Dict[str, Any]:
        """Browser PKCE sign-in. Blocks until callback or timeout."""
        redirect_uri = f"http://127.0.0.1:{port}/auth/callback"
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(32)

        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "socialbot",
        }
        auth_url = f"{AUTH_URL}?{urlencode(params)}"

        result: Dict[str, Any] = {"code": None, "error": None, "done": threading.Event()}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/auth/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                q = parse_qs(parsed.query)
                received_state = (q.get("state") or [None])[0]
                if received_state != state:
                    result["error"] = "state mismatch (CSRF)"
                elif "error" in q:
                    result["error"] = (q.get("error_description") or q.get("error") or ["unknown"])[0]
                else:
                    result["code"] = (q.get("code") or [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                if result["code"]:
                    body = b"<html><body><h1>SocialBot — ChatGPT connected</h1><p>You can close this tab.</p></body></html>"
                else:
                    body = f"<html><body><h1>Sign-in failed</h1><p>{result['error']}</p></body></html>".encode()
                self.wfile.write(body)
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                result["done"].set()

        server = HTTPServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        if open_browser:
            webbrowser.open(auth_url)
        else:
            print(f"Open this URL to sign in:\n{auth_url}\n")

        if not result["done"].wait(timeout=timeout):
            server.shutdown()
            raise TimeoutError("ChatGPT sign-in timed out")

        if result["error"] or not result["code"]:
            raise RuntimeError(result["error"] or "no auth code received")

        token_resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": result["code"],
                "redirect_uri": redirect_uri,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
            timeout=30,
        )
        if not (200 <= token_resp.status_code < 300):
            raise RuntimeError(f"token exchange failed: {token_resp.status_code} {token_resp.text[:300]}")
        self._set_from_response(token_resp.json())
        return self.status()

    def generate(self, prompt: str, model: str = "gpt-4o-mini", n: int = 1) -> List[str]:
        """Generate text using ChatGPT subscription (Codex responses endpoint)."""
        token = self.access_token()
        if not token:
            raise RuntimeError("not signed in — run: socialbot chatgpt login")

        account_id = self.account_id()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
            "originator": "socialbot",
        }
        if account_id:
            headers["ChatGPT-Account-ID"] = account_id

        payload = {
            "model": model,
            "input": prompt,
            "stream": False,
        }
        try:
            r = requests.post(CODEX_RESPONSES_URL, headers=headers, json=payload, timeout=90)
            if r.status_code == 200:
                data = r.json()
                text = _extract_text(data)
                if text:
                    return [text] if n == 1 else [text] * n
            logger.warning("codex responses %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            logger.warning("codex responses failed: %s", e)

        raise RuntimeError(
            f"ChatGPT generation failed (status may require Plus/Pro or model '{model}' unsupported). "
            "Sign-in tokens are valid; try model gpt-4o or check plan limits."
        )


def _extract_text(data: dict) -> str:
    if not data:
        return ""
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    output = data.get("output") or data.get("choices") or []
    parts: List[str] = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                if item.get("type") == "message":
                    for c in item.get("content") or []:
                        if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                            parts.append(c.get("text") or "")
                elif "text" in item:
                    parts.append(str(item["text"]))
                elif "message" in item and isinstance(item["message"], dict):
                    parts.append(item["message"].get("content") or "")
            elif isinstance(item, str):
                parts.append(item)
    if not parts and data.get("choices"):
        for ch in data["choices"]:
            msg = ch.get("message") or {}
            parts.append(msg.get("content") or "")
    return "\n".join(p for p in parts if p).strip()


def get_client(store=None) -> ChatGPTOAuth:
    return ChatGPTOAuth(store=store)
