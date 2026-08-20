"""Background agents — silent growth engines that run on a schedule.

- **Mention & hashtag monitor**: watches queries, meaningfully engages new posts.
- **Trend analyzer**: captures trending topics per platform + drafts posts.
- **Inbox responder**: auto-answers DMs/mentions matching known intents, and
  escalates complaints/unknowns to a webhook.
- **Competitor watch**: tracks competitor accounts, surfaces content gaps and
  drafts posts for uncovered topics.

Every agent honours the safety layer (blacklist/whitelist + rate limiter),
dedupes items it already processed, logs every action to the events log, and
feeds user profiles so growth targeting improves over time.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional

from . import intelligence as nlp
from . import profiles as profiles_mod
from .http import HttpClient
from .models import Post, PostStatus, iso, utcnow
from .platforms import PlatformError, create_platform
from .safety import RateLimiter, Safety
from .storage import Store
from .webhooks import fire_webhook

log = logging.getLogger("socialbot.agents")


def _username(item: Dict[str, Any]) -> str:
    return (item.get("author") or item.get("username") or item.get("user") or "")


class AgentEngine:
    def __init__(self, store: Store, http: Optional[HttpClient] = None):
        self.store = store
        self.http = http or HttpClient()
        self.safety = Safety(store)
        self.limiter = RateLimiter(store)

    # ------------------------------------------------------------ shared bits
    def _platform(self, platform_name: str):
        account = self.store.get_account(platform_name)
        if not account:
            raise PlatformError(f"no account configured for '{platform_name}'")
        return create_platform(platform_name, account.get("config", {}), self.http)

    def _engaged(self, platform, action: str, item: Dict[str, Any], text: str = "") -> bool:
        """Perform one engagement action; raises PlatformError on failure."""
        if action == "like":
            return bool(platform.like(item))
        if action == "follow":
            return bool(platform.follow(item))
        if action == "repost":
            return bool(platform.repost(item))
        if action == "comment":
            return bool(platform.comment(item, text))
        if action == "quote":
            return bool(platform.quote(item, text))
        raise PlatformError(f"unknown action '{action}'")

    def _should_act(self, item: Dict[str, Any], platform_name: str,
                    min_sentiment: float = 0.0, whitelist_only: bool = False,
                    skip_blacklisted: bool = True,
                    interests: str = "") -> bool:
        user = _username(item)
        if not self.safety.allowed(platform_name, user, whitelist_only=whitelist_only,
                                   skip_blacklisted=skip_blacklisted):
            return False
        if interests:
            wanted = [w.lower() for w in interests.split(",") if w.strip()]
            text = ((item.get("text") or "") + " " + (item.get("title") or "")).lower()
            if wanted and not any(w in text for w in wanted):
                return False
        if min_sentiment != 0.0 and nlp.sentiment(item.get("text") or "") < min_sentiment:
            return False
        return True

    # ---------------------------------------------------- mention / hashtag monitor
    def run_mentions(self, rule: Optional[Any] = None,
                     dry_run: Optional[bool] = None) -> List[Dict[str, Any]]:
        monitors = self.store.list_monitors(kind="mention", only_enabled=True)
        if rule is not None:
            monitors = [m for m in monitors if m["rule"].id == rule]
        if not monitors:
            return []

        reports: List[Dict[str, Any]] = []
        for monitor in monitors:
            r = monitor["rule"]
            report = self._run_one_mention(r, dry_run)
            reports.append(report)
        return reports

    def _run_one_mention(self, r: Any, dry_run: Optional[bool]) -> Dict[str, Any]:
        try:
            platform = self._platform(r.platform)
            if "search" not in platform.capabilities:
                raise PlatformError(f"{r.platform} does not support search")
            items = platform.search(r.query, limit=r.limit_per_run)
        except PlatformError as exc:
            r.last_run, r.last_result = iso(utcnow()), {"ok": False, "error": str(exc)}
            self.store.save_monitor("mention", r)
            return r.last_result

        dry = r.dry_run if dry_run is None else dry_run
        acted = skipped = 0
        errors: List[str] = []
        key = f"mention:{r.id}"

        for item in items:
            if acted >= r.limit_per_run:
                skipped += 1
                continue
            remote_id = item.get("id") or item.get("url") or ""
            if r.dedupe and remote_id and self.store.is_seen(key, remote_id):
                skipped += 1
                continue
            if not self._should_act(item, r.platform, min_sentiment=r.min_sentiment,
                                    whitelist_only=r.whitelist_only,
                                    skip_blacklisted=r.skip_blacklisted):
                skipped += 1
                continue
            if not self.limiter.allow(f"rate:{r.platform}:{r.action}"):
                skipped += 1
                continue
            try:
                text = ""
                if r.action in ("comment", "quote"):
                    text = nlp.reply_for(item.get("text") or "", template=r.comment_template)
                if not dry:
                    self._engaged(platform, r.action, item, text)
                    if remote_id:
                        self.store.mark_seen(key, r.platform, remote_id)
                    profiles_mod.observe(self.store, r.platform, _username(item),
                                         item.get("text") or "", action=r.action)
                    time.sleep(random.uniform(1.5, 4.0))
                acted += 1
            except PlatformError as exc:
                errors.append(str(exc))
                skipped += 1

        r.last_run = iso(utcnow())
        r.last_result = {"ok": True, "query": r.query, "found": len(items),
                         "acted": acted, "skipped": skipped, "dry_run": dry,
                         "errors": errors[:5]}
        self.store.save_monitor("mention", r)
        self.store.log_event("agent.mention",
                             f"monitor '{r.name}': {r.action} x{acted} "
                             f"({'dry-run' if dry else 'live'}) on {r.platform}",
                             {"monitor_id": r.id, "acted": acted, "dry_run": dry})
        return r.last_result

    # -------------------------------------------------------------- inbox responder
    def run_inbox(self, rule: Optional[Any] = None) -> List[Dict[str, Any]]:
        rules = self.store.list_inbox_rules(only_enabled=True)
        if rule is not None:
            rules = [x for x in rules if x.id == rule]
        reports: List[Dict[str, Any]] = []
        for r in rules:
            try:
                platform = self._platform(r.platform)
                if "inbox" not in platform.capabilities:
                    raise PlatformError(f"{r.platform} does not support inbox")
                messages = platform.list_messages(limit=r.max_per_run)
            except PlatformError as exc:
                r.last_run, r.last_result = iso(utcnow()), {"ok": False, "error": str(exc)}
                self.store.save_inbox_rule(r)
                reports.append(r.last_result)
                continue

            replied = escalated = unknown = 0
            key = f"inbox:{r.id}"
            for msg in messages:
                mid = msg.get("id") or msg.get("url") or ""
                if mid and self.store.is_seen(key, mid):
                    continue
                text = msg.get("text") or ""
                intent = nlp.detect_intent(text)
                score = nlp.sentiment(text)
                if intent in r.intents and r.auto_reply:
                    reply = nlp.reply_for(text, intent, score, template=r.reply_template)
                    if reply:
                        try:
                            platform.reply_message(msg, reply)
                            replied += 1
                        except PlatformError:
                            pass
                    if mid:
                        self.store.mark_seen(key, r.platform, mid)
                    profiles_mod.observe(self.store, r.platform, _username(msg), text,
                                         action=f"reply:{intent}")
                elif intent == "complaint" or intent == "unknown" or intent == "spam":
                    if intent == "spam":
                        # never reply to spam — remember it and move on
                        if mid:
                            self.store.mark_seen(key, r.platform, mid)
                        unknown += 1
                        continue
                    escalated += 1
                    if mid:
                        self.store.mark_seen(key, r.platform, mid)
                    fire_webhook(r.escalate_webhook, _webhook_payload(
                        "inbox.escalate", r, msg, intent, score))
                    profiles_mod.observe(self.store, r.platform, _username(msg), text,
                                         action="escalated")

            r.last_run = iso(utcnow())
            r.last_result = {"ok": True, "messages": len(messages), "replied": replied,
                             "escalated": escalated, "unknown": unknown}
            self.store.save_inbox_rule(r)
            self.store.log_event(
                "agent.inbox", f"responder '{r.name}': replied {replied}, "
                               f"escalated {escalated}, ignored {unknown}",
                {"rule_id": r.id, "replied": replied, "escalated": escalated})
            reports.append(r.last_result)
        return reports

    # ----------------------------------------------------------- competitor watch
    def run_competitors(self, rule: Optional[Any] = None) -> List[Dict[str, Any]]:
        watches = self.store.list_monitors(kind="competitor", only_enabled=True)
        if rule is not None:
            watches = [w for w in watches if w["rule"].id == rule]
        reports: List[Dict[str, Any]] = []
        for watch in watches:
            r = watch["rule"]
            try:
                platform = self._platform(r.platform)
                if "search" not in platform.capabilities:
                    raise PlatformError(f"{r.platform} does not support search")
            except PlatformError as exc:
                r.last_run, r.last_result = iso(utcnow()), {"ok": False, "error": str(exc)}
                self.store.save_monitor("competitor", r)
                reports.append(r.last_result)
                continue

            own_topics = set()
            for post in self.store.list_posts(limit=500):
                if post.status in ("published", "partial"):
                    own_topics.update(nlp.topics(post.text, 4))
            if r.interests:
                own_topics.update(w.strip().lower() for w in r.interests.split(",") if w.strip())

            recommendations: List[str] = []
            drafts_created = 0
            key = f"comp:{r.id}"
            for competitor in r.competitors:
                try:
                    items = platform.search(competitor, limit=r.limit_per_competitor)
                except PlatformError as exc:
                    recommendations.append(f"{competitor}: search failed ({exc})")
                    continue
                for item in items:
                    if _username(item).lower() != competitor.lower():
                        continue
                    remote_id = item.get("id") or item.get("url") or ""
                    if remote_id and self.store.is_seen(key, remote_id):
                        continue
                    if remote_id:
                        self.store.mark_seen(key, r.platform, remote_id)
                    item_topics = set(nlp.topics(item.get("text") or "", 3))
                    gaps = [t for t in item_topics if t not in own_topics]
                    if not gaps:
                        continue
                    for topic in gaps:
                        recommendations.append(f"{competitor} posted about '{topic}' — "
                                               f"you haven't covered it recently")
                    if r.create_drafts and gaps:
                        from . import ai as ai_mod
                        draft_text = ai_mod.generate(gaps[0], n=1)[0]["text"]
                        draft = Post(text=draft_text, platforms=[],
                                     status=PostStatus.DRAFT.value,
                                     origin=f"competitor:{r.id}",
                                     review_status="pending")
                        self.store.save_post(draft)
                        drafts_created += 1

            r.last_run = iso(utcnow())
            r.last_result = {"ok": True, "competitors": len(r.competitors),
                             "recommendations": len(recommendations),
                             "drafts_created": drafts_created,
                             "top": recommendations[:5]}
            self.store.save_monitor("competitor", r)
            self.store.log_event(
                "agent.competitor", f"watch '{r.name}': {len(recommendations)} gap(s) "
                                    f"found, {drafts_created} draft(s) created",
                {"watch_id": r.id, "recommendations": len(recommendations),
                 "drafts_created": drafts_created})
            reports.append(r.last_result)
        return reports

    # -------------------------------------------------------------- trend analyzer
    def run_trends(self, create_drafts: bool = True,
                   include_real: bool = True) -> List[Dict[str, Any]]:
        from .feeds import capture_trends
        reports = capture_trends(self.store, self.http, create_drafts=create_drafts)
        if include_real:
            try:
                from .trend_analyzer import RealTrendAnalyzer
                analyzer = RealTrendAnalyzer(session=self.http.session)
                reports += analyzer.capture(self.store, create_drafts=create_drafts)
            except Exception as exc:
                reports.append({"platform": "trend-analyzer", "ok": False,
                                "error": str(exc)})
        return reports

    # ------------------------------------------------------------------- run all
    def run_all(self) -> Dict[str, Any]:
        return {
            "mentions": self.run_mentions(),
            "inbox": self.run_inbox(),
            "competitors": self.run_competitors(),
            "trends": self.run_trends(),
        }


def _webhook_payload(event: str, rule: Any, msg: Dict[str, Any],
                     intent: str, score: float) -> Any:
    """Build a Post-like payload for webhook delivery (used by responders)."""
    from .models import Post
    return Post(
        text=f"[{intent} {score:+.2f}] {msg.get('author', '?')}: {msg.get('text', '')[:200]}",
        platforms=[rule.platform], tag="escalation", origin=f"inbox:{rule.id}")