"""Nostr — publish kind-1 text notes to one or more relays (NIP-01).

Requires a hex private key (or nsec bech32). Signing uses the pure-Python
`secp256k1` / Schnorr implementation when available; otherwise falls back to
the optional `coincurve` package. Relays are contacted over WebSocket
(stdlib + optional `websocket-client`).

Minimal deps path: if neither coincurve nor a pure schnorr is present the
adapter still registers and raises a clear PlatformError on publish so the
rest of SocialBot keeps working.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from ..models import Post, PublishResult
from .base import Platform, PlatformError, register

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]


def _bech32_decode_nsec(nsec: str) -> str:
    """Decode nsec1… bech32 to hex private key. Minimal implementation."""
    try:
        from bech32 import bech32_decode, convertbits  # type: ignore
        hrp, data = bech32_decode(nsec)
        if hrp != "nsec" or data is None:
            raise ValueError("not an nsec")
        decoded = convertbits(data, 5, 8, False)
        if not decoded:
            raise ValueError("bad nsec data")
        return bytes(decoded).hex()
    except ImportError:
        raise PlatformError(
            "nsec bech32 keys require the optional 'bech32' package "
            "(pip install bech32). Prefer a 64-char hex private key instead."
        )


def _sign_event(priv_hex: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Compute id + Schnorr sig for a Nostr event. Tries coincurve then pure."""
    pubkey = _pubkey_from_priv(priv_hex)
    created = event.get("created_at") or int(time.time())
    kind = event.get("kind", 1)
    tags = event.get("tags") or []
    content = event.get("content") or ""
    serialized = json.dumps(
        [0, pubkey, created, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    event_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    try:
        from coincurve import PrivateKey  # type: ignore
        pk = PrivateKey(bytes.fromhex(priv_hex))
        sig = pk.sign_schnorr(bytes.fromhex(event_id)).hex()
    except ImportError:
        try:
            from nostr.key import PrivateKey as NostrPK  # type: ignore
            pk = NostrPK(bytes.fromhex(priv_hex))
            from nostr.event import Event  # type: ignore
            ev = Event(content, public_key=pubkey, kind=kind, tags=tags, created_at=created)
            pk.sign_event(ev)
            return {
                "id": ev.id,
                "pubkey": pubkey,
                "created_at": created,
                "kind": kind,
                "tags": tags,
                "content": content,
                "sig": ev.signature,
            }
        except ImportError:
            raise PlatformError(
                "Nostr signing needs either 'coincurve' or 'nostr' "
                "(pip install coincurve). SocialBot keeps the core lightweight."
            )

    return {
        "id": event_id,
        "pubkey": pubkey,
        "created_at": created,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig,
    }


def _pubkey_from_priv(priv_hex: str) -> str:
    try:
        from coincurve import PrivateKey  # type: ignore
        return PrivateKey(bytes.fromhex(priv_hex)).public_key_xonly.hex()
    except ImportError:
        try:
            from nostr.key import PrivateKey as NostrPK  # type: ignore
            return NostrPK(bytes.fromhex(priv_hex)).public_key.hex()
        except ImportError:
            raise PlatformError(
                "Cannot derive Nostr pubkey — install coincurve or nostr"
            )


def _publish_to_relay(relay_url: str, event: Dict[str, Any], timeout: float = 10.0) -> bool:
    """Send [\"EVENT\", event] over WebSocket and look for OK."""
    try:
        import websocket  # type: ignore
    except ImportError:
        raise PlatformError(
            "Nostr needs the optional 'websocket-client' package "
            "(pip install websocket-client)"
        )
    try:
        ws = websocket.create_connection(relay_url, timeout=timeout)
        ws.send(json.dumps(["EVENT", event]))
        ws.settimeout(timeout)
        try:
            raw = ws.recv()
            msg = json.loads(raw)
            if isinstance(msg, list) and len(msg) >= 3 and msg[0] == "OK":
                return bool(msg[2])
            return True
        except Exception:
            return True
        finally:
            ws.close()
    except Exception as exc:
        raise PlatformError(f"relay {relay_url}: {exc}") from exc


@register
class Nostr(Platform):
    name = "nostr"
    display_name = "Nostr"
    color = "#8B5CF6"
    icon = "🟣"
    capabilities = {"post", "search"}
    max_length = 10000
    site = "https://nostr.com"
    docs_url = "https://github.com/nostr-protocol/nips/blob/master/01.md"
    auth_fields = [
        {"key": "private_key", "label": "Private key (hex or nsec1…)", "required": True, "secret": True,
         "help": "64-char hex or nsec bech32. Never share this."},
        {"key": "relays", "label": "Relay URLs (comma-separated)", "required": False, "secret": False,
         "help": "Defaults to damus / nos.lol / nostr.band"},
    ]

    def _priv_hex(self) -> str:
        raw = str(self.require("private_key")).strip()
        if raw.startswith("nsec1"):
            return _bech32_decode_nsec(raw)
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return raw.lower()
        raise PlatformError("private_key must be 64-char hex or nsec1… bech32")

    def _relays(self) -> List[str]:
        raw = self.setting("relays") or ""
        relays = [r.strip() for r in str(raw).split(",") if r.strip()]
        return relays or list(DEFAULT_RELAYS)

    def verify(self) -> tuple:
        try:
            priv = self._priv_hex()
            pub = _pubkey_from_priv(priv)
            return True, f"npub ready (pubkey {pub[:12]}…)"
        except PlatformError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, str(exc)

    def publish(self, post: Post) -> PublishResult:
        text = post.effective_text()
        tags: List[List[str]] = []
        for word in text.split():
            if word.startswith("#") and len(word) > 1:
                tags.append(["t", word[1:].lower()])
        for m in post.media:
            if m.startswith("http"):
                tags.append(["r", m])

        event = _sign_event(self._priv_hex(), {
            "kind": 1,
            "tags": tags,
            "content": text,
            "created_at": int(time.time()),
        })

        ok_relays = []
        errors = []
        for relay in self._relays():
            try:
                if _publish_to_relay(relay, event):
                    ok_relays.append(relay)
            except PlatformError as exc:
                errors.append(str(exc))

        if not ok_relays:
            raise PlatformError("no relay accepted the event: " + "; ".join(errors[:3]))

        note_id = event["id"]
        url = f"https://njump.me/{note_id}"
        return PublishResult(platform=self.name, ok=True, remote_id=note_id, url=url)

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Best-effort search via a public HTTP gateway (no auth needed)."""
        try:
            data = self.http.get_json(
                "https://api.nostr.band/v0/search",
                params={"q": query, "limit": limit},
            )
            out = []
            for ev in (data.get("events") or data if isinstance(data, list) else [])[:limit]:
                out.append({
                    "id": ev.get("id"),
                    "author": ev.get("pubkey", "")[:16],
                    "text": (ev.get("content") or "")[:300],
                    "url": f"https://njump.me/{ev.get('id', '')}",
                })
            return out
        except Exception:
            return []
