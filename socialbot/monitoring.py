"""Monitoring, metrics collection and structured logging.

Ported from PR #3 and reconciled with the existing scheduler/agent engine:
- In-process metrics (counters, gauges, timings) with a bounded ring buffer
- Component health checks with overall status
- Structured JSON logging helper
- System resource monitoring (gracefully degrades when ``psutil`` is absent)
- Operation timing via a context manager

No hard dependencies: if ``psutil`` is not installed the resource monitor
reports the fields it can and health checks stay healthy instead of crashing.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .models import iso, utcnow

log = logging.getLogger("socialbot.monitoring")

try:  # pragma: no cover - optional dependency
    import psutil as _psutil
except Exception:  # pragma: no cover
    _psutil = None


@dataclass
class MetricPoint:
    """A single metric data point."""

    name: str
    value: float
    timestamp: str
    tags: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthStatus:
    """Health state of a single component."""

    component: str
    status: str  # healthy, degraded, unhealthy
    message: str
    latency_ms: Optional[float] = None
    last_check: str = field(default_factory=lambda: iso(utcnow()))
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MetricsCollector:
    """Collects and stores performance metrics in memory (bounded per metric)."""

    def __init__(self, max_points_per_metric: int = 1000):
        self.max_points = max_points_per_metric
        self._metrics: Dict[str, List[MetricPoint]] = defaultdict(list)
        self._lock = threading.RLock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}

    def increment(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            self._counters[name] += value
            self._record(name, float(self._counters[name]), tags or {}, "counter")

    def gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            self._gauges[name] = value
            self._record(name, value, tags or {}, "gauge")

    def timing(self, name: str, duration_ms: float, tags: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            self._record(name, duration_ms, tags or {}, "timing")

    def _record(self, name: str, value: float, tags: Dict[str, str], metric_type: str) -> None:
        key = f"{name}.{metric_type}"
        points = self._metrics[key]
        points.append(MetricPoint(name=key, value=value, timestamp=iso(utcnow()), tags=tags))
        if len(points) > self.max_points:
            self._metrics[key] = points[-self.max_points:]

    def get_metric(self, name: str, limit: int = 100) -> List[MetricPoint]:
        with self._lock:
            return self._metrics.get(name, [])[-limit:]

    def get_counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> Optional[float]:
        with self._lock:
            return self._gauges.get(name)

    def get_all_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {"counters": dict(self._counters), "gauges": dict(self._gauges),
                    "timestamp": iso(utcnow())}

    def export_json(self) -> str:
        with self._lock:
            return json.dumps({
                "exported_at": iso(utcnow()),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "history": {name: [p.to_dict() for p in points[-100:]]
                            for name, points in self._metrics.items()},
            }, indent=2)


class HealthChecker:
    """Runs registered checks and summarizes overall health."""

    def __init__(self):
        self._checks: Dict[str, Callable[[], HealthStatus]] = {}
        self._last_results: Dict[str, HealthStatus] = {}
        self._lock = threading.RLock()

    def register_check(self, name: str, check_func: Callable[[], HealthStatus]) -> None:
        with self._lock:
            self._checks[name] = check_func

    def run_checks(self) -> Dict[str, HealthStatus]:
        results: Dict[str, HealthStatus] = {}
        with self._lock:
            for name, check_func in list(self._checks.items()):
                try:
                    start = time.time()
                    status = check_func()
                    status.latency_ms = round((time.time() - start) * 1000, 2)
                except Exception as e:
                    status = HealthStatus(component=name, status="unhealthy",
                                          message=f"check failed: {e}")
                results[name] = status
                self._last_results[name] = status
        return results

    def get_overall_status(self) -> str:
        with self._lock:
            if not self._last_results:
                return "unknown"
            statuses = [s.status for s in self._last_results.values()]
            if all(s == "healthy" for s in statuses):
                return "healthy"
            if any(s == "unhealthy" for s in statuses):
                return "unhealthy"
            return "degraded"

    def get_health_report(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "overall_status": self.get_overall_status(),
                "components": {name: s.to_dict() for name, s in self._last_results.items()},
                "timestamp": iso(utcnow()),
            }


class StructuredLogger:
    """Wraps a Python logger with structured JSON fields."""

    def __init__(self, logger_name: str = "socialbot"):
        self.logger = logging.getLogger(logger_name)
        self._extra_fields: Dict[str, Any] = {}

    def set_extra(self, **kwargs: Any) -> None:
        self._extra_fields.update(kwargs)

    def clear_extra(self) -> None:
        self._extra_fields.clear()

    def _log(self, level: int, message: str, **kwargs: Any) -> None:
        entry = {"timestamp": iso(utcnow()), "level": logging.getLevelName(level),
                 "message": message, **self._extra_fields, **kwargs}
        self.logger.log(level, message, extra={"structured": entry})

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, **kwargs)

    def event(self, event_type: str, message: str, **kwargs: Any) -> None:
        self.info(message, event_type=event_type, **kwargs)


class ResourceMonitor:
    """Monitors system resources, degrading gracefully without psutil."""

    def __init__(self):
        self._baseline = self._get_resource_usage()

    def _get_resource_usage(self) -> Dict[str, Any]:
        usage: Dict[str, Any] = {"pid": os.getpid(),
                                 "platform": platform.platform()}
        if _psutil is None:
            return usage
        process = _psutil.Process(os.getpid())
        try:
            usage.update({
                "cpu_percent": _psutil.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "memory_rss_mb": process.memory_info().rss / (1024 * 1024),
                "threads": process.num_threads(),
                "open_files": len(process.open_files()),
                "connections": len(process.connections()),
            })
        except Exception:  # pragma: no cover - psutil api drift
            pass
        return usage

    def get_usage(self) -> Dict[str, Any]:
        current = self._get_resource_usage()
        delta = None
        if "memory_rss_mb" in current and "memory_rss_mb" in self._baseline:
            delta = current["memory_rss_mb"] - self._baseline["memory_rss_mb"]
        return {**current, "delta_memory_mb": delta, "timestamp": iso(utcnow())}

    def check_thresholds(self, cpu_threshold: float = 90.0,
                         memory_threshold: float = 90.0) -> List[Dict[str, Any]]:
        usage = self.get_usage()
        alerts: List[Dict[str, Any]] = []
        cpu = usage.get("cpu_percent")
        mem = usage.get("memory_percent")
        if cpu is not None and cpu > cpu_threshold:
            alerts.append({"type": "high_cpu", "value": cpu, "threshold": cpu_threshold,
                           "message": f"CPU usage high: {cpu:.1f}%"})
        if mem is not None and mem > memory_threshold:
            alerts.append({"type": "high_memory", "value": mem, "threshold": memory_threshold,
                           "message": f"Memory usage high: {mem:.1f}%"})
        return alerts


class MonitoringSystem:
    """Centralized monitoring combining metrics, health and resources."""

    _instance: Optional["MonitoringSystem"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "MonitoringSystem":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, log_level: int = logging.INFO):
        if self._initialized:
            return
        self.metrics = MetricsCollector()
        self.health = HealthChecker()
        self.resource_monitor = ResourceMonitor()
        self.logger = StructuredLogger()
        self._setup_logging(log_level)
        self._register_default_health_checks()
        self._initialized = True
        log.info("monitoring system initialized")

    def _setup_logging(self, log_level: int) -> None:
        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                if hasattr(record, "structured"):
                    return json.dumps(record.structured)
                return super().format(record)

        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        ))
        root_logger = logging.getLogger("socialbot")
        root_logger.setLevel(log_level)
        if not root_logger.handlers:
            root_logger.addHandler(handler)

    def _register_default_health_checks(self) -> None:
        self.health.register_check("database", self._check_database)
        self.health.register_check("resources", self._check_resources)
        self.health.register_check("process", self._check_process)

    def _check_database(self) -> HealthStatus:
        try:
            from .storage import Store
            store = Store()
            start = time.time()
            store.list_posts(limit=1)
            return HealthStatus(component="database", status="healthy",
                                message="database responsive",
                                latency_ms=round((time.time() - start) * 1000, 2))
        except Exception as e:
            return HealthStatus(component="database", status="unhealthy",
                                message=f"database error: {e}")

    def _check_resources(self) -> HealthStatus:
        usage = self.resource_monitor.get_usage()
        alerts = self.resource_monitor.check_thresholds()
        if alerts:
            return HealthStatus(component="resources", status="degraded",
                                message="resource thresholds exceeded",
                                details=usage, latency_ms=0)
        return HealthStatus(component="resources", status="healthy",
                            message="resources within normal range",
                            details=usage, latency_ms=0)

    def _check_process(self) -> HealthStatus:
        try:
            if _psutil is not None:
                created = datetime.fromtimestamp(_psutil.Process(os.getpid()).create_time(), timezone.utc)
                uptime = utcnow() - created
                uptime_s = uptime.total_seconds()
            else:
                uptime_s = time.time() - self._baseline.get("_started_at", time.time())
                self._baseline.setdefault("_started_at", time.time())
            return HealthStatus(component="process", status="healthy",
                                message=f"process running (uptime: {uptime_s:.0f}s)",
                                details={"pid": os.getpid(), "platform": platform.platform()},
                                latency_ms=0)
        except Exception as e:
            return HealthStatus(component="process", status="unhealthy",
                                message=f"process check failed: {e}")

    def track_operation(self, operation_name: str) -> "OperationTracker":
        return OperationTracker(self, operation_name)

    def get_full_status(self) -> Dict[str, Any]:
        self.health.run_checks()
        return {
            "health": self.health.get_health_report(),
            "metrics": self.metrics.get_all_metrics(),
            "resources": self.resource_monitor.get_usage(),
            "timestamp": iso(utcnow()),
        }


class OperationTracker:
    """Context manager recording operation timing + success/failure counts."""

    def __init__(self, monitoring: MonitoringSystem, operation_name: str):
        self.monitoring = monitoring
        self.operation_name = operation_name
        self.start_time: Optional[float] = None

    def __enter__(self) -> "OperationTracker":
        self.start_time = time.time()
        self.monitoring.metrics.increment(f"{self.operation_name}.started")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            self.monitoring.metrics.timing(f"{self.operation_name}.duration", duration_ms)
            if exc_type is None:
                self.monitoring.metrics.increment(f"{self.operation_name}.success")
            else:
                self.monitoring.metrics.increment(f"{self.operation_name}.failure")
                self.monitoring.logger.error(f"operation {self.operation_name} failed",
                                             error=str(exc_val), duration_ms=round(duration_ms, 2))
        return False


# ------------------------------------------------------------------ helpers
def get_monitoring() -> MonitoringSystem:
    return MonitoringSystem()


def track_event(event_type: str, message: str, **kwargs: Any) -> None:
    get_monitoring().logger.event(event_type, message, **kwargs)


def increment_metric(name: str, value: int = 1, **tags: Any) -> None:
    get_monitoring().metrics.increment(name, value, tags or None)


def record_gauge(name: str, value: float, **tags: Any) -> None:
    get_monitoring().metrics.gauge(name, value, tags or None)