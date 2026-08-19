"""Publishing engine: takes a Post, fans it out to platforms, records results,
fires webhooks and handles retries/recurrence (Postiz-style pipeline)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .http import HttpClient
from .models import Post, PostStatus, PublishResult, iso, parse_dt, utcnow
from .platforms import PlatformError, create_platform
from .storage import Store
from .webhooks import fire_webhook

log = logging.getLogger("socialbot.publisher")


class Publisher:
    def __init__(self, store: Store, http: Optional[HttpClient] = None):
        self.store = store
        self.http = http or HttpClient()

    # ------------------------------------------------------------------ util
    def _platform_for(self, name: str, account: Optional[Dict[str, Any]] = None):
        config = (account or {}).get("config", {}) if account else {}
        return create_platform(name, config, self.http)

    def account_signature(self, platform: str) -> Optional[str]:
        account = self.store.get_account(platform)
        return (account or {}).get("config", {}).get("signature")

    # -------------------------------------------------------------- publish
    def publish_now(self, post: Post, store: bool = True,
                    previous_results: Optional[Dict[str, Dict[str, Any]]] = None) -> Post:
        """Immediately publish *post* to every configured platform it targets.

        ``previous_results`` (used by :meth:`retry`) keeps earlier successes for
        platforms not re-attempted, so partial state isn't lost.
        """
        post.status = PostStatus.PUBLISHING.value
        if store:
            self.store.save_post(post)
        self.store.log_event("publish.start", f"publishing '{post.text[:40]}…' to "
                                              f"{', '.join(post.platforms)}", {"post_id": post.id})

        results: Dict[str, Dict[str, Any]] = {}
        succeeded: List[str] = []
        failed: Dict[str, str] = {}

        for platform_name in post.platforms:
            try:
                account = self.store.get_account(platform_name)
                platform = self._platform_for(platform_name, account)
                sig = (account or {}).get("config", {}).get("signature")
                result = platform.publish(post)
                results[platform_name] = result.to_dict()
                if result.ok:
                    succeeded.append(platform_name)
                    self.store.log_event("publish.ok",
                                         f"published to {platform_name}: {result.url or result.remote_id}",
                                         {"post_id": post.id, "platform": platform_name})
            except PlatformError as exc:
                failed[platform_name] = str(exc)
                results[platform_name] = PublishResult(
                    platform=platform_name, ok=False, error=str(exc)).to_dict()
                log.warning("publish %s -> %s failed: %s", post.id, platform_name, exc)
                self.store.log_event("publish.fail", f"{platform_name}: {exc}",
                                     {"post_id": post.id, "platform": platform_name})
            except Exception as exc:  # unexpected — keep going
                failed[platform_name] = f"unexpected error: {exc}"
                results[platform_name] = PublishResult(
                    platform=platform_name, ok=False, error=str(exc)).to_dict()
                log.exception("unexpected publish error on %s", platform_name)

        # keep results from earlier attempts for platforms not in this run
        for name, prior in (previous_results or {}).items():
            if name not in results:
                results[name] = prior
                if prior.get("ok") and name not in succeeded:
                    succeeded.append(name)

        post.results = results
        post.attempts += 1
        post.published_at = iso(utcnow())

        if succeeded and not failed:
            post.status = PostStatus.PUBLISHED.value
        elif succeeded and failed:
            post.status = PostStatus.PARTIAL.value
            post.error = "; ".join(f"{k}: {v}" for k, v in failed.items())[:1000]
        else:
            post.status = PostStatus.FAILED.value
            post.error = "; ".join(f"{k}: {v}" for k, v in failed.items())[:1000]

        if store:
            self.store.save_post(post)

        # recurring post -> queue the next occurrence
        if post.status in (PostStatus.PUBLISHED.value, PostStatus.PARTIAL.value):
            self.schedule_next_occurrence(post)

        # fire webhook (per-post override or account default)
        if post.status in (PostStatus.PUBLISHED.value, PostStatus.PARTIAL.value):
            fire_webhook(post.webhook_url, post)
        return post

    # ------------------------------------------------------------- retrying
    def retry(self, post_id: str) -> Optional[Post]:
        post = self.store.get_post(post_id)
        if not post:
            return None
        if post.status not in (PostStatus.FAILED.value, PostStatus.PARTIAL.value):
            return post
        previous = dict(post.results or {})
        retry_platforms = [p for p in post.platforms
                           if not post.results.get(p, {}).get("ok")]
        post.platforms = retry_platforms or post.platforms
        post.error = None
        return self.publish_now(post, previous_results=previous)

    def process_failed(self, limit: int = 20) -> List[Post]:
        """Autonomously retry failed posts with exponential backoff.

        A failed post is retried once ``2 ** attempts`` minutes have passed since
        its last attempt (2m, 4m, 8m, … capped at 1h) and attempts remain.
        """
        now = utcnow()
        retried: List[Post] = []
        for post in self.store.list_posts(limit=2000):
            if post.status != PostStatus.FAILED.value or post.attempts >= post.max_attempts:
                continue
            if len(retried) >= limit:
                break
            last = parse_dt(post.published_at) or parse_dt(post.created_at) or now
            delay = min(60 * (2 ** max(post.attempts, 1)), 3600)
            if (now - last).total_seconds() < delay:
                continue
            retried.append(self.retry(post.id))
        if retried:
            log.info("auto-retried %d failed post(s)", len(retried))
        return [r for r in retried if r]

    # ---------------------------------------------------------- recurrence
    def schedule_next_occurrence(self, post: Post) -> Optional[Post]:
        """For recurring posts, queue the next occurrence after a publish."""
        rec = post.recurrence or {}
        if not rec.get("type"):
            return None

        if rec["type"] == "interval":
            from datetime import timedelta
            seconds = int(rec.get("value", 86400))
            nxt = utcnow() + timedelta(seconds=seconds)
        elif rec["type"] == "cron":
            try:
                from apscheduler.triggers.cron import CronTrigger
                trigger = CronTrigger.from_crontab(str(rec.get("value", "0 9 * * *")))
                nxt = trigger.get_next_fire_time(None, utcnow())
            except Exception as exc:  # pragma: no cover
                log.warning("cron recurrence failed: %s", exc)
                return None
        else:
            return None
        if not nxt:
            return None

        clone = Post(
            text=post.text, media=post.media, platforms=post.platforms,
            status=PostStatus.SCHEDULED.value, scheduled_at=iso(nxt),
            recurrence=post.recurrence, tag=post.tag, webhook_url=post.webhook_url)
        self.store.save_post(clone)
        return clone

    # ------------------------------------------------------- due processing
    def process_due(self) -> List[Post]:
        """Publish every post whose scheduled time has arrived."""
        due = self.store.due_posts(iso(utcnow()))
        processed: List[Post] = []
        for post in due:
            scheduled = parse_dt(post.scheduled_at)
            if scheduled and scheduled > utcnow():
                continue
            self.publish_now(post)   # also queues the next recurrence if any
            processed.append(post)
        return processed
