"""Scheduler — ticks every N seconds, publishes due posts, auto-retries failed
ones, refreshes metrics and runs the background agents (mentions, inbox,
competitor watch, trend capture, feeds) on their own intervals.

Runs either standalone (``socialbot run``) or embedded in the API server so the
web dashboard is always in sync.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .agents import AgentEngine
from .analytics import refresh_metrics
from .bot import BotEngine
from .models import iso, utcnow
from .publisher import Publisher
from .storage import Store

log = logging.getLogger("socialbot.scheduler")

TICK_SECONDS = 20
METRICS_MINUTES = 360  # refresh engagement numbers every 6h
BOT_MINUTES = int(os.environ.get("SOCIALBOT_BOT_INTERVAL", "0") or 0)
AGENTS_MINUTES = int(os.environ.get("SOCIALBOT_AGENTS_INTERVAL", "30") or 30)
FEEDS_MINUTES = int(os.environ.get("SOCIALBOT_FEEDS_INTERVAL", "60") or 60)
TRENDS_MINUTES = int(os.environ.get("SOCIALBOT_TRENDS_INTERVAL", "120") or 120)
REPORT_HOUR = int(os.environ.get("SOCIALBOT_REPORT_HOUR", "6") or 6)


class Scheduler:
    """Owns a BackgroundScheduler that processes the due-post queue."""

    def __init__(self, store: Store, publisher: Optional[Publisher] = None,
                 tick_seconds: int = TICK_SECONDS):
        self.store = store
        self.publisher = publisher or Publisher(store)
        self.tick_seconds = tick_seconds
        self._scheduler: Optional[BackgroundScheduler] = None
        self._lock = threading.Lock()
        self.running = False

    # ------------------------------------------------------------------ life
    def start(self) -> None:
        with self._lock:
            if self._scheduler:
                return
            self._scheduler = BackgroundScheduler(timezone="UTC")
            self._scheduler.add_job(self._tick, IntervalTrigger(seconds=self.tick_seconds),
                                    id="tick", max_instances=1, coalesce=True,
                                    next_run_time=utcnow())
            self._scheduler.add_job(self._refresh_metrics,
                                    IntervalTrigger(minutes=METRICS_MINUTES),
                                    id="metrics", max_instances=1, coalesce=True)
            if BOT_MINUTES > 0:
                self._scheduler.add_job(self._run_bot_rules,
                                        IntervalTrigger(minutes=BOT_MINUTES),
                                        id="bot", max_instances=1, coalesce=True)
            if AGENTS_MINUTES > 0:
                self._scheduler.add_job(self._run_agents,
                                        IntervalTrigger(minutes=AGENTS_MINUTES),
                                        id="agents", max_instances=1, coalesce=True)
            if FEEDS_MINUTES > 0:
                self._scheduler.add_job(self._run_feeds,
                                        IntervalTrigger(minutes=FEEDS_MINUTES),
                                        id="feeds", max_instances=1, coalesce=True)
            if TRENDS_MINUTES > 0:
                self._scheduler.add_job(self._run_trends,
                                        IntervalTrigger(minutes=TRENDS_MINUTES),
                                        id="trends", max_instances=1, coalesce=True)
            self._scheduler.add_job(self._monthly_report,
                                    CronTrigger(day=1, hour=REPORT_HOUR),
                                    id="report", max_instances=1, coalesce=True)
            self._scheduler.start()
            self.running = True
            self.store.log_event("scheduler.start", f"scheduler running "
                                                    f"(tick={self.tick_seconds}s"
                                                    f"{f', bot every {BOT_MINUTES}m' if BOT_MINUTES else ''}"
                                                    f"{f', agents every {AGENTS_MINUTES}m' if AGENTS_MINUTES else ''}"
                                                    f"{f', feeds every {FEEDS_MINUTES}m' if FEEDS_MINUTES else ''}"
                                                    f"{f', trends every {TRENDS_MINUTES}m' if TRENDS_MINUTES else ''})")
            log.info("scheduler started (tick=%ss%s%s%s%s)", self.tick_seconds,
                     f", bot every {BOT_MINUTES}m" if BOT_MINUTES else "",
                     f", agents every {AGENTS_MINUTES}m" if AGENTS_MINUTES else "",
                     f", feeds every {FEEDS_MINUTES}m" if FEEDS_MINUTES else "",
                     f", trends every {TRENDS_MINUTES}m" if TRENDS_MINUTES else "")

    def stop(self) -> None:
        with self._lock:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None
            self.running = False
        log.info("scheduler stopped")

    def status(self) -> dict:
        return {
            "running": self.running,
            "tick_seconds": self.tick_seconds,
            "bot_interval_minutes": BOT_MINUTES,
            "agents_interval_minutes": AGENTS_MINUTES,
            "feeds_interval_minutes": FEEDS_MINUTES,
            "trends_interval_minutes": TRENDS_MINUTES,
            "now": iso(utcnow()),
            "pending": len(self.store.list_posts(status="scheduled")),
        }

    # ------------------------------------------------------------------ jobs
    def _tick(self) -> None:
        try:
            processed = self.publisher.process_due()
            if processed:
                log.info("processed %d due post(s)", len(processed))
            retried = self.publisher.process_failed()
            if retried:
                log.info("auto-retried %d failed post(s)", len(retried))
        except Exception:  # pragma: no cover - keep the scheduler alive
            log.exception("scheduler tick failed")

    def _run_bot_rules(self) -> None:  # pragma: no cover - optional job
        try:
            results = BotEngine(self.store, self.publisher.http).run_all()
            log.info("bot rules ran: %d rule(s)", len(results))
        except Exception:
            log.exception("scheduled bot rules failed")

    def _run_agents(self) -> None:  # pragma: no cover - optional job
        try:
            results = AgentEngine(self.store, self.publisher.http).run_all()
            log.info("agents ran: %d mention(s), %d inbox, %d competitor(s), %d trend(s)",
                     len(results["mentions"]), len(results["inbox"]),
                     len(results["competitors"]), len(results["trends"]))
        except Exception:
            log.exception("scheduled agents failed")

    def _run_feeds(self) -> None:  # pragma: no cover - optional job
        try:
            from .feeds import run_feed
            for feed in self.store.list_feeds(only_enabled=True):
                run_feed(feed, self.store, self.publisher.http)
        except Exception:
            log.exception("scheduled feed pull failed")

    def _run_trends(self) -> None:  # pragma: no cover - optional job
        try:
            AgentEngine(self.store, self.publisher.http).run_trends()
        except Exception:
            log.exception("scheduled trend capture failed")

    def _monthly_report(self) -> None:  # pragma: no cover - optional job
        try:
            from .reports import save_and_deliver
            save_and_deliver(self.store)
        except Exception:
            log.exception("scheduled monthly report failed")

    def _refresh_metrics(self) -> None:
        try:
            refresh_metrics(self.store, self.publisher.http)
        except Exception:  # pragma: no cover
            log.exception("metrics refresh failed")

    def run_forever(self) -> None:  # pragma: no cover - CLI entry
        import time
        self.start()
        try:
            while True:
                time.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            self.stop()