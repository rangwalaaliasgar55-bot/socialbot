"""Multi-agent coordination and concurrency management.

This module provides:
- Agent registration and tracking
- Distributed locking for database operations
- Task queue management
- Agent health monitoring
- Load balancing across agents
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from .models import iso, utcnow

log = logging.getLogger("socialbot.agents")

DEFAULT_AGENT_HEARTBEAT_INTERVAL = 30  # seconds
DEFAULT_AGENT_TIMEOUT = 90  # seconds without heartbeat = dead
DEFAULT_LOCK_TIMEOUT = 30  # seconds


@dataclass
class AgentInfo:
    """Information about a running agent."""
    agent_id: str
    hostname: str
    pid: int
    started_at: str
    last_heartbeat: str
    status: str = "active"  # active, idle, busy, dead
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
    """A task in the queue."""
    task_id: str
    task_type: str  # publish, bot_run, analytics_refresh, etc.
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
        # Ensure payload has a default
        if 'payload' not in d and 'payload_json' in d:
            import json
            d['payload'] = json.loads(d['payload_json']) if d['payload_json'] else {}
        elif 'payload' not in d:
            d['payload'] = {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class AgentCoordinator:
    """Coordinates multiple agents running concurrently.
    
    Provides:
    - Agent registration and heartbeat tracking
    - Distributed locking via SQLite
    - Task queue for work distribution
    - Dead agent detection and cleanup
    """

    def __init__(self, store_path: Optional[str] = None):
        self.store_path = store_path or os.environ.get("SOCIALBOT_DB", "socialbot.db")
        self.agent_id = os.environ.get("AGENT_ID", f"agent_{uuid.uuid4().hex[:8]}")
        self.hostname = os.environ.get("HOSTNAME", "unknown")
        self.pid = os.getpid()
        self._local = threading.local()
        self._lock = threading.RLock()
        self._init_tables()
        self._register_agent()

    def _get_conn(self):
        import sqlite3
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.store_path, timeout=30)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_tables(self):
        """Initialize coordination tables."""
        conn = self._get_conn()
        conn.executescript("""
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
        """)
        conn.commit()

    def _register_agent(self):
        """Register this agent in the database."""
        conn = self._get_conn()
        now = iso(utcnow())
        conn.execute("""
            INSERT INTO agents (agent_id, hostname, pid, started_at, last_heartbeat, status, metadata_json)
            VALUES (?, ?, ?, ?, ?, 'active', '{}')
            ON CONFLICT(agent_id) DO UPDATE SET
                hostname=excluded.hostname,
                pid=excluded.pid,
                started_at=excluded.started_at,
                last_heartbeat=excluded.last_heartbeat,
                status='active'
        """, (self.agent_id, self.hostname, self.pid, now, now))
        conn.commit()
        log.info("Agent %s registered (hostname=%s, pid=%d)", self.agent_id, self.hostname, self.pid)

    def heartbeat(self, status: str = "active", current_task: Optional[str] = None):
        """Send a heartbeat to indicate this agent is alive."""
        conn = self._get_conn()
        now = iso(utcnow())
        if current_task:
            conn.execute("""
                UPDATE agents 
                SET last_heartbeat=?, status=?, current_task=?
                WHERE agent_id=?
            """, (now, status, current_task, self.agent_id))
        else:
            conn.execute("""
                UPDATE agents 
                SET last_heartbeat=?, status=?
                WHERE agent_id=?
            """, (now, status, self.agent_id))
        conn.commit()

    def unregister_agent(self):
        """Mark this agent as stopped."""
        conn = self._get_conn()
        conn.execute("""
            UPDATE agents SET status='stopped', last_heartbeat=?
            WHERE agent_id=?
        """, (iso(utcnow()), self.agent_id))
        conn.commit()
        log.info("Agent %s unregistered", self.agent_id)

    def cleanup_dead_agents(self) -> List[str]:
        """Detect and mark dead agents (no heartbeat within timeout)."""
        conn = self._get_conn()
        timeout_threshold = (utcnow() - timedelta(seconds=DEFAULT_AGENT_TIMEOUT)).isoformat()
        
        # Find dead agents
        rows = conn.execute("""
            SELECT agent_id FROM agents 
            WHERE status='active' AND last_heartbeat < ?
        """, (timeout_threshold,)).fetchall()
        
        dead_agents = [row["agent_id"] for row in rows]
        
        # Mark them as dead
        for agent_id in dead_agents:
            conn.execute("""
                UPDATE agents SET status='dead' WHERE agent_id=?
            """, (agent_id,))
            
            # Release their locks
            conn.execute("""
                DELETE FROM locks WHERE agent_id=?
            """, (agent_id,))
            
            # Release their claimed tasks back to pending
            conn.execute("""
                UPDATE task_queue 
                SET status='pending', claimed_by=NULL, claimed_at=NULL
                WHERE claimed_by=? AND status='claimed'
            """, (agent_id,))
        
        conn.commit()
        
        if dead_agents:
            log.warning("Detected %d dead agents: %s", len(dead_agents), dead_agents)
        
        return dead_agents

    @contextmanager
    def acquire_lock(self, lock_name: str, timeout: int = DEFAULT_LOCK_TIMEOUT):
        """Acquire a distributed lock.
        
        Usage:
            with coordinator.acquire_lock("publish"):
                # do protected work
        """
        conn = self._get_conn()
        now = utcnow()
        expires_at = now + timedelta(seconds=timeout)
        
        # Try to acquire the lock
        acquired = False
        for _ in range(3):  # retry a few times
            # First, clean up expired locks
            conn.execute("""
                DELETE FROM locks WHERE expires_at < ?
            """, (iso(now),))
            
            # Try to insert/update the lock
            try:
                conn.execute("""
                    INSERT INTO locks (lock_name, agent_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(lock_name) DO UPDATE SET
                        agent_id=excluded.agent_id,
                        acquired_at=excluded.acquired_at,
                        expires_at=excluded.expires_at
                    WHERE agent_id=? OR expires_at < ?
                """, (lock_name, self.agent_id, iso(now), iso(expires_at), 
                      self.agent_id, iso(now)))
                
                # Verify we got the lock
                row = conn.execute("""
                    SELECT agent_id FROM locks WHERE lock_name=?
                """, (lock_name,)).fetchone()
                
                if row and row["agent_id"] == self.agent_id:
                    acquired = True
                    break
            except Exception:
                pass
            
            time.sleep(0.1)  # brief wait before retry
        
        if not acquired:
            raise RuntimeError(f"Failed to acquire lock '{lock_name}'")
        
        try:
            yield True
        finally:
            # Release the lock
            conn.execute("""
                DELETE FROM locks WHERE lock_name=? AND agent_id=?
            """, (lock_name, self.agent_id))
            conn.commit()

    def enqueue_task(self, task_type: str, payload: Dict[str, Any], 
                     priority: int = 0, max_retries: int = 3) -> str:
        """Add a task to the queue."""
        conn = self._get_conn()
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = iso(utcnow())
        
        conn.execute("""
            INSERT INTO task_queue (task_id, task_type, payload_json, priority, 
                                    status, created_at, max_retries)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """, (task_id, task_type, json.dumps(payload), priority, now, max_retries))
        conn.commit()
        
        log.info("Enqueued task %s (type=%s, priority=%d)", task_id, task_type, priority)
        return task_id

    def claim_task(self, task_types: Optional[List[str]] = None) -> Optional[Task]:
        """Claim the next available task from the queue."""
        conn = self._get_conn()
        now = iso(utcnow())
        
        # Build query based on task types filter
        if task_types:
            placeholders = ','.join('?' * len(task_types))
            where_clause = f"status='pending' AND task_type IN ({placeholders})"
            params = list(task_types)
        else:
            where_clause = "status='pending'"
            params = []
        
        # Get the highest priority pending task
        row = conn.execute(f"""
            SELECT * FROM task_queue 
            WHERE {where_clause}
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        """, params).fetchone()
        
        if not row:
            return None
        
        task_id = row["task_id"]
        
        # Claim it
        conn.execute("""
            UPDATE task_queue 
            SET status='claimed', claimed_by=?, claimed_at=?
            WHERE task_id=? AND status='pending'
        """, (self.agent_id, now, task_id))
        conn.commit()
        
        # Verify we got it
        updated = conn.execute("""
            SELECT * FROM task_queue WHERE task_id=?
        """, (task_id,)).fetchone()
        
        if not updated or updated["claimed_by"] != self.agent_id:
            return None  # Another agent grabbed it
        
        task = Task.from_dict(dict(updated))
        log.info("Agent %s claimed task %s", self.agent_id, task_id)
        return task

    def complete_task(self, task_id: str, result: Dict[str, Any]):
        """Mark a task as completed."""
        conn = self._get_conn()
        now = iso(utcnow())
        
        conn.execute("""
            UPDATE task_queue 
            SET status='completed', completed_at=?, result_json=?
            WHERE task_id=?
        """, (now, json.dumps(result), task_id))
        conn.commit()
        
        # Update agent stats
        conn.execute("""
            UPDATE agents SET tasks_completed=tasks_completed+1 WHERE agent_id=?
        """, (self.agent_id,))
        conn.commit()
        
        log.info("Task %s completed successfully", task_id)

    def fail_task(self, task_id: str, error: str):
        """Mark a task as failed, potentially requeueing it."""
        conn = self._get_conn()
        task = self.get_task(task_id)
        
        if not task:
            return
        
        now = iso(utcnow())
        
        if task.retry_count < task.max_retries:
            # Requeue for retry
            conn.execute("""
                UPDATE task_queue 
                SET status='pending', claimed_by=NULL, claimed_at=NULL,
                    retry_count=retry_count+1, error=?
                WHERE task_id=?
            """, (error, task_id))
            log.info("Task %s requeued for retry (%d/%d)", task_id, 
                    task.retry_count + 1, task.max_retries)
        else:
            # Mark as permanently failed
            conn.execute("""
                UPDATE task_queue 
                SET status='failed', completed_at=?, error=?
                WHERE task_id=?
            """, (now, error, task_id))
            
            # Update agent stats
            conn.execute("""
                UPDATE agents SET tasks_failed=tasks_failed+1 WHERE agent_id=?
            """, (self.agent_id,))
            
            log.error("Task %s permanently failed after %d retries: %s", 
                     task_id, task.max_retries, error)
        
        conn.commit()

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT * FROM task_queue WHERE task_id=?
        """, (task_id,)).fetchone()
        
        return Task.from_dict(dict(row)) if row else None

    def list_tasks(self, status: Optional[str] = None, 
                   limit: int = 100) -> List[Task]:
        """List tasks, optionally filtered by status."""
        conn = self._get_conn()
        
        if status:
            rows = conn.execute("""
                SELECT * FROM task_queue 
                WHERE status=?
                ORDER BY priority DESC, created_at DESC
                LIMIT ?
            """, (status, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM task_queue 
                ORDER BY priority DESC, created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        
        return [Task.from_dict(dict(row)) for row in rows]

    def list_agents(self, include_dead: bool = False) -> List[AgentInfo]:
        """List all registered agents."""
        conn = self._get_conn()
        
        if include_dead:
            rows = conn.execute("""
                SELECT * FROM agents ORDER BY last_heartbeat DESC
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM agents 
                WHERE status IN ('active', 'idle', 'busy')
                ORDER BY last_heartbeat DESC
            """).fetchall()
        
        return [AgentInfo.from_dict(dict(row)) for row in rows]

    def get_agent_stats(self) -> Dict[str, Any]:
        """Get overall system statistics."""
        conn = self._get_conn()
        
        active_agents = conn.execute("""
            SELECT COUNT(*) FROM agents WHERE status='active'
        """).fetchone()[0]
        
        pending_tasks = conn.execute("""
            SELECT COUNT(*) FROM task_queue WHERE status='pending'
        """).fetchone()[0]
        
        claimed_tasks = conn.execute("""
            SELECT COUNT(*) FROM task_queue WHERE status='claimed'
        """).fetchone()[0]
        
        completed_today = conn.execute("""
            SELECT COUNT(*) FROM task_queue 
            WHERE status='completed' AND completed_at >= date('now')
        """).fetchone()[0]
        
        failed_today = conn.execute("""
            SELECT COUNT(*) FROM task_queue 
            WHERE status='failed' AND completed_at >= date('now')
        """).fetchone()[0]
        
        return {
            "active_agents": active_agents,
            "pending_tasks": pending_tasks,
            "claimed_tasks": claimed_tasks,
            "completed_today": completed_today,
            "failed_today": failed_today,
            "timestamp": iso(utcnow())
        }

    def start_heartbeat_thread(self, interval: int = DEFAULT_AGENT_HEARTBEAT_INTERVAL):
        """Start a background thread to send periodic heartbeats."""
        def heartbeat_loop():
            while True:
                try:
                    self.heartbeat()
                    self.cleanup_dead_agents()
                except Exception as e:
                    log.exception("Heartbeat error: %s", e)
                time.sleep(interval)
        
        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()
        return thread


# Global coordinator instance (lazy initialization)
_coordinator: Optional[AgentCoordinator] = None
_coordinator_lock = threading.Lock()


def get_coordinator(store_path: Optional[str] = None) -> AgentCoordinator:
    """Get or create the global agent coordinator."""
    global _coordinator
    
    with _coordinator_lock:
        if _coordinator is None:
            _coordinator = AgentCoordinator(store_path)
            _coordinator.start_heartbeat_thread()
        return _coordinator


@contextmanager
def distributed_lock(lock_name: str, timeout: int = DEFAULT_LOCK_TIMEOUT):
    """Context manager for acquiring a distributed lock."""
    coordinator = get_coordinator()
    with coordinator.acquire_lock(lock_name, timeout):
        yield
