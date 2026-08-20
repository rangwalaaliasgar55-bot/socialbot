"""Multi-agent coordination & concurrency management.

Port of the coordination layer proposed in PR #3, reconciled with the
v1.2.0 agent engine in :mod:`socialbot.agents`. The engine decides *what*
work to do (mentions, inbox, competitors, trends); this module decides
*how* many concurrent workers can do it safely:

- Agent registration, heartbeats and dead-agent detection
- Distributed locks backed by SQLite (safe across processes/threads)
- A persistent task queue with claiming, retries and completion tracking

It only depends on the stdlib (plus the existing SQLite store), so it runs
anywhere without new packages.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .models import iso, utcnow

log = logging.getLogger("socialbot.coordination")

DEFAULT_AGENT_HEARTBEAT_INTERVAL = 30  # seconds
DEFAULT_AGENT_TIMEOUT = 90  # seconds without heartbeat = dead
DEFAULT_LOCK_TIMEOUT = 30  # seconds


@dataclass
class AgentInfo:
    """Information about a running agent worker."""

    agent_id: str
    hostname: str
    pid: int
    started_at: str
    last_heartbeat: str
    status: str = "active"  # active, idle, busy, dead, stopped
    current_task: Optional[str] = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentInfo":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Task:
    """A unit of work in the shared queue."""

    task_id: str
    task_type: str  # publish, bot_run, analytics_refresh, ...
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # higher = more urgent
    status: str = "pending"  # pending, claimed, completed, failed
    claimed_by: Optional[str] = None
    claimed_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: iso(utcnow()))
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Task":
        if "payload" not in d and "payload_json" in d:
            d["payload"] = json.loads(d["payload_json"]) if d["payload_json"] else {}
        elif "payload" not in d:
            d["payload"] = {}
        if "result" not in d and "result_json" in d:
            d["result"] = json.loads(d["result_json"]) if d["result_json"] else None
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class AgentCoordinator:
    """Coordinates multiple agents running concurrently.

    Provides agent registration/heartbeats, distributed locking via SQLite
    and a persistent task queue. All state lives in the same database the
    store uses, so workers in different processes cooperate correctly.
    """

    def __init__(self, store: Any = None, store_path: Optional[str] = None):
        if store is not None:
            self.store_path = getattr(store, "path", None) or store_path
        else:
            self.store_path = store_path or os.environ.get("SOCIALBOT_DB", "socialbot.db")
        self.agent_id = os.environ.get("AGENT_ID", f"agent_{uuid.uuid4().hex[:8]}")
        self.hostname = os.environ.get("HOSTNAME", "unknown")
        self.pid = os.getpid()
        self._local = threading.local()
        self._lock = threading.RLock()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()
        self._init_tables()
        self._register_agent()

    # ------------------------------------------------------------- connection
    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.store_path, timeout=30)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _close_conn(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                self._local.conn = None

    # ----------------------------------------------------------------- tables
    def _init_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                pid INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                last_heartbeat TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                current_task TEXT,
                tasks_completed INTEGER NOT NULL DEFAULT 0,
                tasks_failed INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
            CREATE INDEX IF NOT EXISTS idx_agents_heartbeat ON agents(last_heartbeat);

            CREATE TABLE IF NOT EXISTS locks (
                lock_name TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_locks_expires ON locks(expires_at);

            CREATE TABLE IF NOT EXISTS task_queue (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                claimed_by TEXT,
                claimed_at TEXT,
                completed_at TEXT,
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3
            );
            CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status);
            CREATE INDEX IF NOT EXISTS idx_task_priority ON task_queue(priority DESC, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_task_claimed ON task_queue(claimed_by);
            """
        )
        conn.commit()

    # ------------------------------------------------------------------ agent
    def _register_agent(self) -> None:
        conn = self._get_conn()
        now = iso(utcnow())
        conn.execute(
            """
            INSERT INTO agents (agent_id, hostname, pid, started_at, last_heartbeat, status, metadata_json)
            VALUES (?, ?, ?, ?, ?, 'active', '{}')
            ON CONFLICT(agent_id) DO UPDATE SET
                hostname=excluded.hostname,
                pid=excluded.pid,
                started_at=excluded.started_at,
                last_heartbeat=excluded.last_heartbeat,
                status='active'
            """,
            (self.agent_id, self.hostname, self.pid, now, now),
        )
        conn.commit()
        log.info("agent %s registered (hostname=%s, pid=%d)", self.agent_id, self.hostname, self.pid)

    def heartbeat(self, status: str = "active", current_task: Optional[str] = None) -> None:
        conn = self._get_conn()
        now = iso(utcnow())
        if current_task:
            conn.execute(
                "UPDATE agents SET last_heartbeat=?, status=?, current_task=? WHERE agent_id=?",
                (now, status, current_task, self.agent_id),
            )
        else:
            conn.execute(
                "UPDATE agents SET last_heartbeat=?, status=? WHERE agent_id=?",
                (now, status, self.agent_id),
            )
        conn.commit()

    def unregister_agent(self) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE agents SET status='stopped', last_heartbeat=? WHERE agent_id=?",
            (iso(utcnow()), self.agent_id),
        )
        conn.commit()
        self._close_conn()
        log.info("agent %s unregistered", self.agent_id)

    def cleanup_dead_agents(self) -> List[str]:
        """Detect agents that stopped heartbeating and release their resources."""
        conn = self._get_conn()
        threshold = (utcnow() - timedelta(seconds=DEFAULT_AGENT_TIMEOUT)).isoformat()
        dead = [
            row["agent_id"]
            for row in conn.execute(
                "SELECT agent_id FROM agents WHERE status='active' AND last_heartbeat < ?",
                (threshold,),
            ).fetchall()
        ]
        for agent_id in dead:
            conn.execute("UPDATE agents SET status='dead' WHERE agent_id=?", (agent_id,))
            conn.execute("DELETE FROM locks WHERE agent_id=?", (agent_id,))
            conn.execute(
                "UPDATE task_queue SET status='pending', claimed_by=NULL, claimed_at=NULL "
                "WHERE claimed_by=? AND status='claimed'",
                (agent_id,),
            )
        conn.commit()
        if dead:
            log.warning("detected %d dead agent(s): %s", len(dead), dead)
        return dead

    # ------------------------------------------------------------------ locks
    @contextmanager
    def acquire_lock(self, lock_name: str, timeout: int = DEFAULT_LOCK_TIMEOUT):
        """Acquire a distributed lock (yields ``True`` while holding it).

        Usage::

            with coordinator.acquire_lock("publish"):
                # protected work
        """
        conn = self._get_conn()
        now = utcnow()
        expires_at = now + timedelta(seconds=timeout)
        acquired = False
        for _ in range(3):
            try:
                conn.execute("DELETE FROM locks WHERE expires_at < ?", (iso(now),))
                conn.execute(
                    """
                    INSERT INTO locks (lock_name, agent_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(lock_name) DO UPDATE SET
                        agent_id=excluded.agent_id,
                        acquired_at=excluded.acquired_at,
                        expires_at=excluded.expires_at
                    WHERE agent_id=? OR expires_at < ?
                    """,
                    (lock_name, self.agent_id, iso(now), iso(expires_at),
                     self.agent_id, iso(now)),
                )
                row = conn.execute(
                    "SELECT agent_id FROM locks WHERE lock_name=?", (lock_name,)
                ).fetchone()
                if row and row["agent_id"] == self.agent_id:
                    conn.commit()  # make the lock durable before yielding
                    acquired = True
                    break
                conn.rollback()  # not ours — release the write txn we opened
            except sqlite3.Error:
                conn.rollback()
            time.sleep(0.1)
        if not acquired:
            raise RuntimeError(f"failed to acquire lock '{lock_name}'")
        try:
            yield True
        finally:
            try:
                conn.execute(
                    "DELETE FROM locks WHERE lock_name=? AND agent_id=?",
                    (lock_name, self.agent_id),
                )
                conn.commit()
            except sqlite3.Error:
                conn.rollback()

    # ------------------------------------------------------------------ tasks
    def enqueue_task(self, task_type: str, payload: Dict[str, Any],
                     priority: int = 0, max_retries: int = 3) -> str:
        conn = self._get_conn()
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO task_queue (task_id, task_type, payload_json, priority, status, created_at, max_retries) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (task_id, task_type, json.dumps(payload), priority, iso(utcnow()), max_retries),
        )
        conn.commit()
        log.info("enqueued task %s (type=%s, priority=%d)", task_id, task_type, priority)
        return task_id

    def claim_task(self, task_types: Optional[List[str]] = None) -> Optional[Task]:
        conn = self._get_conn()
        now = iso(utcnow())
        if task_types:
            placeholders = ",".join("?" * len(task_types))
            where, params = f"status='pending' AND task_type IN ({placeholders})", list(task_types)
        else:
            where, params = "status='pending'", []
        row = conn.execute(
            f"SELECT * FROM task_queue WHERE {where} "
            "ORDER BY priority DESC, created_at ASC LIMIT 1",
            params,
        ).fetchone()
        if not row:
            return None
        task_id = row["task_id"]
        conn.execute(
            "UPDATE task_queue SET status='claimed', claimed_by=?, claimed_at=? "
            "WHERE task_id=? AND status='pending'",
            (self.agent_id, now, task_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM task_queue WHERE task_id=?", (task_id,)
        ).fetchone()
        if not updated or updated["claimed_by"] != self.agent_id:
            return None  # another worker grabbed it first
        log.info("agent %s claimed task %s", self.agent_id, task_id)
        return Task.from_dict(dict(updated))

    def complete_task(self, task_id: str, result: Dict[str, Any]) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE task_queue SET status='completed', completed_at=?, result_json=? WHERE task_id=?",
            (iso(utcnow()), json.dumps(result), task_id),
        )
        conn.execute("UPDATE agents SET tasks_completed=tasks_completed+1 WHERE agent_id=?", (self.agent_id,))
        conn.commit()
        log.info("task %s completed", task_id)

    def fail_task(self, task_id: str, error: str) -> None:
        conn = self._get_conn()
        task = self.get_task(task_id)
        if not task:
            return
        now = iso(utcnow())
        if task.retry_count < task.max_retries:
            conn.execute(
                "UPDATE task_queue SET status='pending', claimed_by=NULL, claimed_at=NULL, "
                "retry_count=retry_count+1, error=? WHERE task_id=?",
                (error, task_id),
            )
            log.info("task %s requeued for retry (%d/%d)", task_id, task.retry_count + 1, task.max_retries)
        else:
            conn.execute(
                "UPDATE task_queue SET status='failed', completed_at=?, error=? WHERE task_id=?",
                (now, error, task_id),
            )
            conn.execute("UPDATE agents SET tasks_failed=tasks_failed+1 WHERE agent_id=?", (self.agent_id,))
            log.error("task %s permanently failed after %d retries: %s", task_id, task.max_retries, error)
        conn.commit()

    def get_task(self, task_id: str) -> Optional[Task]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM task_queue WHERE task_id=?", (task_id,)).fetchone()
        return Task.from_dict(dict(row)) if row else None

    def list_tasks(self, status: Optional[str] = None, limit: int = 100) -> List[Task]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM task_queue WHERE status=? ORDER BY priority DESC, created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_queue ORDER BY priority DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Task.from_dict(dict(row)) for row in rows]

    def list_agents(self, include_dead: bool = False) -> List[AgentInfo]:
        conn = self._get_conn()
        if include_dead:
            rows = conn.execute("SELECT * FROM agents ORDER BY last_heartbeat DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agents WHERE status IN ('active', 'idle', 'busy') "
                "ORDER BY last_heartbeat DESC"
            ).fetchall()
        return [AgentInfo.from_dict(dict(row)) for row in rows]

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        def count(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "active_agents": count("SELECT COUNT(*) FROM agents WHERE status='active'"),
            "pending_tasks": count("SELECT COUNT(*) FROM task_queue WHERE status='pending'"),
            "claimed_tasks": count("SELECT COUNT(*) FROM task_queue WHERE status='claimed'"),
            "completed_today": count("SELECT COUNT(*) FROM task_queue WHERE status='completed' "
                                     "AND completed_at >= datetime('now', 'start of day')"),
            "failed_today": count("SELECT COUNT(*) FROM task_queue WHERE status='failed' "
                                  "AND completed_at >= datetime('now', 'start of day')"),
            "timestamp": iso(utcnow()),
        }

    # ------------------------------------------------------------- heartbeat
    def start_heartbeat_thread(self, interval: int = DEFAULT_AGENT_HEARTBEAT_INTERVAL) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def loop() -> None:
            while not self._stopping.is_set():
                try:
                    self.heartbeat()
                    self.cleanup_dead_agents()
                except Exception:
                    log.exception("heartbeat error")
                time.sleep(interval)

        self._stopping.clear()
        self._heartbeat_thread = threading.Thread(target=loop, daemon=True)
        self._heartbeat_thread.start()
        log.info("heartbeat thread started for agent %s", self.agent_id)

    def shutdown(self) -> None:
        self._stopping.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)
        try:
            self.unregister_agent()
        except Exception:
            log.exception("unregister on shutdown failed")


# ------------------------------------------------------------------ helpers
_coordinator: Optional[AgentCoordinator] = None
_coordinator_lock = threading.Lock()


def get_coordinator(store: Any = None, store_path: Optional[str] = None) -> AgentCoordinator:
    """Get the process-wide coordinator, starting its heartbeat thread once."""
    global _coordinator
    with _coordinator_lock:
        if _coordinator is None:
            _coordinator = AgentCoordinator(store=store, store_path=store_path)
            _coordinator.start_heartbeat_thread()
        return _coordinator


def shutdown_coordinator() -> None:
    global _coordinator
    with _coordinator_lock:
        if _coordinator is not None:
            _coordinator.shutdown()
            _coordinator = None


@contextmanager
def distributed_lock(lock_name: str, timeout: int = DEFAULT_LOCK_TIMEOUT, store: Any = None):
    """Context manager wrapping :func:`AgentCoordinator.acquire_lock`."""
    coordinator = get_coordinator(store=store)
    with coordinator.acquire_lock(lock_name, timeout):
        yield