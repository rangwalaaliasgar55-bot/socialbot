"""Scheduler — ticks every N seconds, publishes due posts and refreshes metrics.

Runs either standalone (``socialbot run``) or embedded in the API server so the
web dashboard is always in sync.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional, Set

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .analytics import refresh_metrics
from .models import iso, utcnow
from .publisher import Publisher
from .storage import Store

log = logging.getLogger("socialbot.scheduler")

TICK_SECONDS = 20
METRICS_MINUTES = 360  # refresh engagement numbers every 6h


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
            self._scheduler.start()
            self.running = True
            self.store.log_event("scheduler.start", f"scheduler running "
                                                    f"(tick={self.tick_seconds}s)")
            log.info("scheduler started (tick=%ss)", self.tick_seconds)

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
            "now": iso(utcnow()),
            "pending": len(self.store.list_posts(status="scheduled")),
        }

    # ------------------------------------------------------------------ jobs
    def _tick(self) -> None:
        try:
            processed = self.publisher.process_due()
            if processed:
                log.info("processed %d due post(s)", len(processed))
        except Exception:  # pragma: no cover - keep the scheduler alive
            log.exception("scheduler tick failed")

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
