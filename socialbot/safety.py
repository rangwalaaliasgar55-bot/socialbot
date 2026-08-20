"""Ethical & safe growth — rate limiting and blacklist/whitelist enforcement.

A persistent token-bucket limiter (per platform/action) keeps us under
platform thresholds even across restarts, and blacklist/whitelist rules from
the dashboard decide who the agents may *never* (or *must always*) engage.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from .models import SafetyRule, iso, parse_dt, utcnow
from .storage import Store

log = logging.getLogger("socialbot.safety")

# Default tokens-per-minute per platform/action. Safe, modest defaults — every
# agent run consumes tokens so repeated runs can never exceed the rate.
DEFAULT_RATE = float(os.environ.get("SOCIALBOT_RATE_PER_MINUTE", "12") or 12)


class RateLimiter:
    """Persistent token bucket. ``allow(key)`` returns True while tokens remain."""

    def __init__(self, store: Store, per_minute: float = DEFAULT_RATE):
        self.store = store
        self.per_minute = per_minute

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = utcnow()
        bucket = self.store.get_bucket(key)
        if not bucket:
            if self.per_minute >= cost:
                self.store.save_bucket(key, self.per_minute - cost, iso(now))
                return True
            self.store.save_bucket(key, self.per_minute, iso(now))
            return False

        last = parse_dt(bucket["last_refill"]) or now
        seconds = max(0, (now - last).total_seconds())
        tokens = min(self.per_minute, bucket["tokens"] + seconds * (self.per_minute / 60.0))
        if tokens < cost:
            self.store.save_bucket(key, tokens, iso(now))
            return False
        self.store.save_bucket(key, tokens - cost, iso(now))
        return True

    def remaining(self, key: str) -> float:
        now = utcnow()
        bucket = self.store.get_bucket(key)
        if not bucket:
            return self.per_minute
        last = parse_dt(bucket["last_refill"]) or now
        seconds = max(0, (now - last).total_seconds())
        return min(self.per_minute, bucket["tokens"] + seconds * (self.per_minute / 60.0))


class Safety:
    """Blacklist / whitelist helpers used by the bot and the agents."""

    def __init__(self, store: Store):
        self.store = store
        self._cache: Optional[Dict[str, Dict[str, set]]] = None

    def _load(self) -> None:
        rules = self.store.list_safety_rules()
        cache: Dict[str, Dict[str, set]] = {"blacklist": {"*": set()},
                                            "whitelist": {"*": set()}}
        for rule in rules:
            cache.setdefault(rule.list_type, {}).setdefault(rule.platform or "*", set())
            cache[rule.list_type][rule.platform or "*"].add(rule.username.lower())
        self._cache = cache

    def refresh(self) -> None:
        self._load()

    def is_blacklisted(self, platform: str, username: str) -> bool:
        return self._check("blacklist", platform, username)

    def is_whitelisted(self, platform: str, username: str) -> bool:
        return self._check("whitelist", platform, username)

    def _check(self, list_type: str, platform: str, username: str) -> bool:
        if self._cache is None:
            self._load()
        assert self._cache is not None
        name = (username or "").lower().lstrip("@")
        return (name in self._cache.get(list_type, {}).get("*", set())
                or name in self._cache.get(list_type, {}).get(platform, set()))

    def allowed(self, platform: str, username: str, *,
                whitelist_only: bool = False, skip_blacklisted: bool = True) -> bool:
        """True when this account may be engaged."""
        if not username:
            return True
        if whitelist_only and not self.is_whitelisted(platform, username):
            return False
        if skip_blacklisted and self.is_blacklisted(platform, username):
            return False
        return True

    def add(self, list_type: str, platform: str, username: str, note: str = "") -> SafetyRule:
        rule = SafetyRule(list_type=list_type if list_type in ("blacklist", "whitelist")
                          else "blacklist", platform=platform or "", username=username,
                          note=note)
        self.store.save_safety_rule(rule)
        self._load()
        return rule

    def list(self, list_type: Optional[str] = None) -> List[SafetyRule]:
        return self.store.list_safety_rules(list_type)

    def remove(self, rule_id: str) -> bool:
        ok = self.store.delete_safety_rule(rule_id)
        self._load()
        return ok