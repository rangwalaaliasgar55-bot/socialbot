"""Growth bot engine — rule-driven automation (like / follow / comment / repost).

Rules watch a keyword or hashtag search on platforms that support it and perform
capped actions with per-run / per-hour limits and a dry-run mode, so you can
grow an audience the way the popular Python bot repos do — but through official
APIs only (platform ToS compliant, like Postiz).
"""
from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .http import HttpClient
from .models import BotRule, iso, utcnow
from .platforms import PlatformError, create_platform
from .storage import Store

log = logging.getLogger("socialbot.bot")

COMMENT_TEMPLATES = [
    "Great point about {topic}!",
    "This resonates — thanks for sharing about {topic}.",
    "Interesting take on {topic}.",
    "Love this. Following for more {topic} content!",
]


class BotEngine:
    def __init__(self, store: Store, http: Optional[HttpClient] = None):
        self.store = store
        self.http = http or HttpClient()

    # ------------------------------------------------------------------ run
    def run_rule(self, rule: BotRule, dry_run: Optional[bool] = None) -> Dict[str, Any]:
        """Execute one rule once. Returns a run report."""
        account = self.store.get_account(rule.platform)
        if not account:
            return {"ok": False, "error": f"no account configured for '{rule.platform}'"}
        platform = create_platform(rule.platform, account.get("config", {}), self.http)

        action = rule.action.lower()
        if action not in platform.capabilities:
            return {"ok": False,
                    "error": f"{rule.platform} does not support '{action}' "
                             f"(supports: {', '.join(sorted(platform.capabilities))})"}

        query = rule.trigger_value
        if rule.trigger_type == "hashtag" and not query.startswith("#"):
            query = f"#{query}"
        if action == "follow":
            query = query.lstrip("#")  # search for people/topics instead of posts

        try:
            items = platform.search(query, limit=rule.limit_per_run)
        except PlatformError as exc:
            rule.last_run, rule.last_result = iso(utcnow()), {"ok": False, "error": str(exc)}
            self.store.save_rule(rule)
            return rule.last_result

        dry = rule.dry_run if dry_run is None else dry_run
        acted, skipped, errors = 0, 0, []
        # keep inside the hourly budget (real actions only, dry-runs don't count)
        budget = max(0, rule.limit_per_hour - self._recent_actions(rule))

        for item in items:
            if acted >= min(rule.limit_per_run, budget):
                skipped += 1
                continue
            topic = self._topic_from(query)
            if action == "comment" and not rule.comment_template:
                template = random.choice(COMMENT_TEMPLATES)
            elif action == "comment":
                template = rule.comment_template
            else:
                template = ""

            try:
                if dry:
                    acted += 1
                    continue
                if action == "like":
                    platform.like(item)
                elif action == "follow":
                    platform.follow(item)
                elif action == "repost":
                    platform.repost(item)
                elif action == "comment":
                    platform.comment(item, template.format(topic=topic))
                acted += 1
                time.sleep(random.uniform(1.5, 4.0))  # human-ish pacing
            except PlatformError as exc:
                errors.append(str(exc))
                skipped += 1

        rule.last_run = iso(utcnow())
        rule.last_result = {"ok": True, "action": action, "query": query,
                            "found": len(items), "acted": acted,
                            "dry_run": dry, "skipped": skipped, "errors": errors[:5]}
        rule.total_actions += acted
        self.store.save_rule(rule)
        self.store.log_event("bot.run", f"rule '{rule.name}': {action} x{acted} "
                                        f"({'dry-run' if dry else 'live'}) on {rule.platform}",
                             {"rule_id": rule.id, "acted": acted, "dry_run": dry})
        return rule.last_result

    def run_all(self, dry_run: Optional[bool] = None) -> List[Dict[str, Any]]:
        return [self.run_rule(rule, dry_run) for rule in self.store.list_rules(only_enabled=True)]

    # ---------------------------------------------------------------- helpers
    def _recent_actions(self, rule: BotRule) -> int:
        """Count *live* actions for this rule in the last hour.

        Replayed from the events log (every run logs `acted` + `dry_run`), so
        repeated runs inside the hour are all counted — unlike a naive
        "last run only" check this enforces the true per-hour cap.
        """
        cutoff = utcnow() - timedelta(hours=1)
        count = 0
        for event in self.store.list_events(limit=500):
            if event["type"] != "bot.run":
                continue
            data = event.get("data") or {}
            if data.get("rule_id") != rule.id:
                continue
            if data.get("dry_run"):
                continue
            ts = event.get("ts")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt > cutoff:
                count += int(data.get("acted", 0))
        return count

    @staticmethod
    def _topic_from(query: str) -> str:
        words = re.sub(r"[#@]", "", query).split()
        return " ".join(w for w in words if not w.startswith("-"))[:60] or "this"
