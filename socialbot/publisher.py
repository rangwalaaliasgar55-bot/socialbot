"""Publishing engine: takes a Post, fans it out to platforms, records results,
fires webhooks and handles retries/recurrence (Postiz-style pipeline).

Enhanced with:
- Distributed locking for multi-agent coordination
- Task queue integration
- Performance monitoring and metrics
- Structured logging
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .http import HttpClient
from .models import Post, PostStatus, PublishResult, iso, parse_dt, utcnow
from .platforms import PlatformError, create_platform
from .storage import Store
from .webhooks import fire_webhook
from .agents import get_coordinator, distributed_lock
from .monitoring import get_monitoring, track_event, increment_metric, record_gauge

log = logging.getLogger("socialbot.publisher")


class Publisher:
    def __init__(self, store: Store, http: Optional[HttpClient] = None):
        self.store = store
        self.http = http or HttpClient()
        self.monitoring = get_monitoring()
        
        # Try to get coordinator, but work without it if not available
        try:
            self.coordinator = get_coordinator()
            self.use_coordination = True
        except Exception:
            self.coordinator = None
            self.use_coordination = False
            log.info("Running in single-agent mode (no coordinator)")

    # ------------------------------------------------------------------ util
    def _platform_for(self, name: str, account: Optional[Dict[str, Any]] = None):
        config = (account or {}).get("config", {}) if account else {}
        return create_platform(name, config, self.http)

    def account_signature(self, platform: str) -> Optional[str]:
        account = self.store.get_account(platform)
        return (account or {}).get("config", {}).get("signature")

    # -------------------------------------------------------------- publish
    def publish_now(self, post: Post, store: bool = True) -> Post:
        """Immediately publish *post* to every configured platform it targets."""
        with self.monitoring.track_operation("publish"):
            # Use distributed lock if coordinator is available
            if self.use_coordination:
                lock_ctx = self.coordinator.acquire_lock(f"publish_{post.id}")
            else:
                from contextlib import nullcontext
                lock_ctx = nullcontext()
            
            with lock_ctx:
                return self._do_publish(post, store)
    
    def _do_publish(self, post: Post, store: bool = True) -> Post:
        """Internal publish implementation."""
        post.status = PostStatus.PUBLISHING.value
        if store:
            self.store.save_post(post)
        
        # Track with structured logging
        track_event("publish.start", f"publishing '{post.text[:40]}…' to {', '.join(post.platforms)}", 
                   post_id=post.id, platforms=post.platforms)
        increment_metric("publish.started")

        results: Dict[str, Dict[str, Any]] = {}
        succeeded: List[str] = []
        failed: Dict[str, str] = {}
        platform_times: Dict[str, float] = {}

        for platform_name in post.platforms:
            import time
            start_time = time.time()
            
            try:
                account = self.store.get_account(platform_name)
                platform = self._platform_for(platform_name, account)
                sig = (account or {}).get("config", {}).get("signature")
                result = platform.publish(post)
                elapsed_ms = (time.time() - start_time) * 1000
                platform_times[platform_name] = elapsed_ms
                
                results[platform_name] = result.to_dict()
                if result.ok:
                    succeeded.append(platform_name)
                    self.store.log_event("publish.ok",
                                         f"published to {platform_name}: {result.url or result.remote_id}",
                                         {"post_id": post.id, "platform": platform_name})
                    increment_metric("publish.platform.success", tags={"platform": platform_name})
                    record_gauge(f"publish.duration.{platform_name}", elapsed_ms)
                else:
                    failed[platform_name] = result.error or "unknown error"
                    increment_metric("publish.platform.failure", tags={"platform": platform_name})
            except PlatformError as exc:
                elapsed_ms = (time.time() - start_time) * 1000
                failed[platform_name] = str(exc)
                results[platform_name] = PublishResult(
                    platform=platform_name, ok=False, error=str(exc)).to_dict()
                log.warning("publish %s -> %s failed: %s", post.id, platform_name, exc)
                self.store.log_event("publish.fail", f"{platform_name}: {exc}",
                                     {"post_id": post.id, "platform": platform_name})
                increment_metric("publish.platform.error", tags={"platform": platform_name, "error_type": "PlatformError"})
            except Exception as exc:  # unexpected — keep going
                elapsed_ms = (time.time() - start_time) * 1000
                failed[platform_name] = f"unexpected error: {exc}"
                results[platform_name] = PublishResult(
                    platform=platform_name, ok=False, error=str(exc)).to_dict()
                log.exception("unexpected publish error on %s", platform_name)
                increment_metric("publish.platform.error", tags={"platform": platform_name, "error_type": "Unexpected"})

        post.results = results
        post.attempts += 1
        post.published_at = iso(utcnow())

        if succeeded and not failed:
            post.status = PostStatus.PUBLISHED.value
            increment_metric("publish.completed.success")
        elif succeeded and failed:
            post.status = PostStatus.PARTIAL.value
            post.error = "; ".join(f"{k}: {v}" for k, v in failed.items())[:1000]
            increment_metric("publish.completed.partial")
        else:
            post.status = PostStatus.FAILED.value
            post.error = "; ".join(f"{k}: {v}" for k, v in failed.items())[:1000]
            increment_metric("publish.completed.failed")

        if store:
            self.store.save_post(post)

        # recurring post -> queue the next occurrence
        if post.status in (PostStatus.PUBLISHED.value, PostStatus.PARTIAL.value):
            self.schedule_next_occurrence(post)

        # fire webhook (per-post override or account default)
        if post.status in (PostStatus.PUBLISHED.value, PostStatus.PARTIAL.value):
            fire_webhook(post.webhook_url, post)
        
        # Record total duration
        total_platforms = len(post.platforms)
        record_gauge("publish.total_platforms", total_platforms)
        record_gauge("publish.successful_platforms", len(succeeded))
        
        return post

    # ------------------------------------------------------------- retrying
    def retry(self, post_id: str) -> Optional[Post]:
        post = self.store.get_post(post_id)
        if not post:
            return None
        if post.status not in (PostStatus.FAILED.value, PostStatus.PARTIAL.value):
            return post
        retry_platforms = [p for p in post.platforms
                           if not post.results.get(p, {}).get("ok")]
        post.platforms = retry_platforms or post.platforms
        post.error = None
        return self.publish_now(post)

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
        with self.monitoring.track_operation("process_due"):
            due = self.store.due_posts(iso(utcnow()))
            processed: List[Post] = []
            
            increment_metric("process_due.checked", len(due))
            
            for post in due:
                scheduled = parse_dt(post.scheduled_at)
                if scheduled and scheduled > utcnow():
                    continue
                
                try:
                    self.publish_now(post)   # also queues the next recurrence if any
                    processed.append(post)
                    increment_metric("process_due.published")
                except Exception as e:
                    log.exception("Error processing due post %s: %s", post.id, e)
                    increment_metric("process_due.failed")
            
            record_gauge("process_due.processed_count", len(processed))
            return processed
