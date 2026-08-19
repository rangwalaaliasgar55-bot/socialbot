"""Enhanced monitoring, metrics collection, and structured logging.

This module provides:
- Structured JSON logging for agent activities
- Performance metrics collection
- Health check endpoints
- System resource monitoring
- Alerting capabilities
"""
from __future__ import annotations

import json
import logging
import os
import platform
import psutil
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Callable

from .models import iso, utcnow

log = logging.getLogger("socialbot.monitoring")


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
    """System health status."""
    component: str
    status: str  # healthy, degraded, unhealthy
    message: str
    latency_ms: Optional[float] = None
    last_check: str = field(default_factory=lambda: iso(utcnow()))
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MetricsCollector:
    """Collects and stores performance metrics."""
    
    def __init__(self, max_points_per_metric: int = 1000):
        self.max_points = max_points_per_metric
        self._metrics: Dict[str, List[MetricPoint]] = defaultdict(list)
        self._lock = threading.RLock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        
    def increment(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
        """Increment a counter metric."""
        with self._lock:
            self._counters[name] += value
            self._record_point(name, float(self._counters[name]), tags or {}, metric_type="counter")
    
    def gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Set a gauge metric."""
        with self._lock:
            self._gauges[name] = value
            self._record_point(name, value, tags or {}, metric_type="gauge")
    
    def timing(self, name: str, duration_ms: float, tags: Optional[Dict[str, str]] = None):
        """Record a timing metric."""
        with self._lock:
            self._record_point(name, duration_ms, tags or {}, metric_type="timing")
    
    def _record_point(self, name: str, value: float, tags: Dict[str, str], metric_type: str):
        """Record a metric data point."""
        point = MetricPoint(
            name=f"{name}.{metric_type}",
            value=value,
            timestamp=iso(utcnow()),
            tags=tags
        )
        
        points = self._metrics[name]
        points.append(point)
        
        # Trim old points
        if len(points) > self.max_points:
            self._metrics[name] = points[-self.max_points:]
    
    def get_metric(self, name: str, limit: int = 100) -> List[MetricPoint]:
        """Get recent data points for a metric."""
        with self._lock:
            points = self._metrics.get(name, [])
            return points[-limit:]
    
    def get_counter(self, name: str) -> int:
        """Get current counter value."""
        with self._lock:
            return self._counters.get(name, 0)
    
    def get_gauge(self, name: str) -> Optional[float]:
        """Get current gauge value."""
        with self._lock:
            return self._gauges.get(name)
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all current metrics."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timestamp": iso(utcnow())
            }
    
    def export_json(self) -> str:
        """Export metrics as JSON."""
        with self._lock:
            data = {
                "exported_at": iso(utcnow()),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "history": {
                    name: [p.to_dict() for p in points[-100:]]
                    for name, points in self._metrics.items()
                }
            }
            return json.dumps(data, indent=2)


class HealthChecker:
    """Performs health checks on system components."""
    
    def __init__(self):
        self._checks: Dict[str, Callable[[], HealthStatus]] = {}
        self._last_results: Dict[str, HealthStatus] = {}
        self._lock = threading.RLock()
        
    def register_check(self, name: str, check_func: Callable[[], HealthStatus]):
        """Register a health check function."""
        with self._lock:
            self._checks[name] = check_func
    
    def run_checks(self) -> Dict[str, HealthStatus]:
        """Run all registered health checks."""
        results = {}
        
        with self._lock:
            for name, check_func in self._checks.items():
                try:
                    start = time.time()
                    status = check_func()
                    elapsed = (time.time() - start) * 1000
                    status.latency_ms = round(elapsed, 2)
                    results[name] = status
                    self._last_results[name] = status
                except Exception as e:
                    status = HealthStatus(
                        component=name,
                        status="unhealthy",
                        message=f"Check failed: {str(e)}"
                    )
                    results[name] = status
                    self._last_results[name] = status
        
        return results
    
    def get_overall_status(self) -> str:
        """Get overall system health status."""
        with self._lock:
            if not self._last_results:
                return "unknown"
            
            statuses = [s.status for s in self._last_results.values()]
            
            if all(s == "healthy" for s in statuses):
                return "healthy"
            elif any(s == "unhealthy" for s in statuses):
                return "unhealthy"
            else:
                return "degraded"
    
    def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report."""
        with self._lock:
            return {
                "overall_status": self.get_overall_status(),
                "components": {
                    name: status.to_dict() 
                    for name, status in self._last_results.items()
                },
                "timestamp": iso(utcnow())
            }


class StructuredLogger:
    """Structured JSON logger for agent activities."""
    
    def __init__(self, logger_name: str = "socialbot"):
        self.logger = logging.getLogger(logger_name)
        self._extra_fields: Dict[str, Any] = {}
        
    def set_extra(self, **kwargs):
        """Set extra fields to include in all log messages."""
        self._extra_fields.update(kwargs)
    
    def clear_extra(self):
        """Clear extra fields."""
        self._extra_fields.clear()
    
    def _log(self, level: int, message: str, **kwargs):
        """Log a structured message."""
        extra = {**self._extra_fields, **kwargs}
        
        log_entry = {
            "timestamp": iso(utcnow()),
            "level": logging.getLevelName(level),
            "message": message,
            **extra
        }
        
        # Add structured data to log record
        record_extra = {"structured": log_entry}
        self.logger.log(level, message, extra=record_extra)
    
    def info(self, message: str, **kwargs):
        """Log an info message."""
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log a warning message."""
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log an error message."""
        self._log(logging.ERROR, message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """Log a debug message."""
        self._log(logging.DEBUG, message, **kwargs)
    
    def event(self, event_type: str, message: str, **kwargs):
        """Log a structured event."""
        self.info(message, event_type=event_type, **kwargs)


class ResourceMonitor:
    """Monitors system resources."""
    
    def __init__(self):
        self._baseline = self._get_resource_usage()
    
    def _get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage."""
        process = psutil.Process(os.getpid())
        
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": process.memory_percent(),
            "memory_rss_mb": process.memory_info().rss / (1024 * 1024),
            "threads": process.num_threads(),
            "open_files": len(process.open_files()),
            "connections": len(process.connections()),
        }
    
    def get_usage(self) -> Dict[str, Any]:
        """Get current resource usage with delta from baseline."""
        current = self._get_resource_usage()
        
        return {
            **current,
            "delta_memory_mb": current["memory_rss_mb"] - self._baseline["memory_rss_mb"],
            "timestamp": iso(utcnow())
        }
    
    def check_thresholds(self, 
                        cpu_threshold: float = 90.0,
                        memory_threshold: float = 90.0) -> List[Dict[str, Any]]:
        """Check if resource usage exceeds thresholds."""
        alerts = []
        usage = self.get_usage()
        
        if usage["cpu_percent"] > cpu_threshold:
            alerts.append({
                "type": "high_cpu",
                "value": usage["cpu_percent"],
                "threshold": cpu_threshold,
                "message": f"CPU usage high: {usage['cpu_percent']:.1f}%"
            })
        
        if usage["memory_percent"] > memory_threshold:
            alerts.append({
                "type": "high_memory",
                "value": usage["memory_percent"],
                "threshold": memory_threshold,
                "message": f"Memory usage high: {usage['memory_percent']:.1f}%"
            })
        
        return alerts


class MonitoringSystem:
    """Centralized monitoring system combining all components."""
    
    _instance: Optional["MonitoringSystem"] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
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
        
        log.info("Monitoring system initialized")
    
    def _setup_logging(self, log_level: int):
        """Configure structured logging."""
        handler = logging.StreamHandler()
        
        # Create formatter that outputs JSON for structured logs
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                if hasattr(record, 'structured'):
                    return json.dumps(record.structured)
                return super().format(record)
        
        handler.setFormatter(JsonFormatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
        ))
        
        root_logger = logging.getLogger("socialbot")
        root_logger.setLevel(log_level)
        
        if not root_logger.handlers:
            root_logger.addHandler(handler)
    
    def _register_default_health_checks(self):
        """Register default health checks."""
        self.health.register_check("database", self._check_database)
        self.health.register_check("resources", self._check_resources)
        self.health.register_check("process", self._check_process)
    
    def _check_database(self) -> HealthStatus:
        """Check database connectivity."""
        try:
            from .storage import Store
            store = Store()
            start = time.time()
            store.list_posts(limit=1)
            elapsed = (time.time() - start) * 1000
            
            return HealthStatus(
                component="database",
                status="healthy",
                message=f"Database responsive ({elapsed:.1f}ms)",
                latency_ms=round(elapsed, 2)
            )
        except Exception as e:
            return HealthStatus(
                component="database",
                status="unhealthy",
                message=f"Database error: {str(e)}"
            )
    
    def _check_resources(self) -> HealthStatus:
        """Check system resources."""
        usage = self.resource_monitor.get_usage()
        alerts = self.resource_monitor.check_thresholds()
        
        if alerts:
            return HealthStatus(
                component="resources",
                status="degraded",
                message="Resource thresholds exceeded",
                details=usage,
                latency_ms=0
            )
        
        return HealthStatus(
            component="resources",
            status="healthy",
            message="Resources within normal range",
            details=usage,
            latency_ms=0
        )
    
    def _check_process(self) -> HealthStatus:
        """Check process health."""
        try:
            process = psutil.Process(os.getpid())
            uptime = datetime.now(timezone.utc) - datetime.fromtimestamp(process.create_time(), timezone.utc)
            
            return HealthStatus(
                component="process",
                status="healthy",
                message=f"Process running (uptime: {str(uptime).split('.')[0]})",
                details={
                    "pid": os.getpid(),
                    "uptime_seconds": uptime.total_seconds(),
                    "platform": platform.platform()
                },
                latency_ms=0
            )
        except Exception as e:
            return HealthStatus(
                component="process",
                status="unhealthy",
                message=f"Process check failed: {str(e)}"
            )
    
    def track_operation(self, operation_name: str):
        """Context manager to track operation timing."""
        return OperationTracker(self, operation_name)
    
    def get_full_status(self) -> Dict[str, Any]:
        """Get complete system status."""
        self.health.run_checks()
        
        return {
            "health": self.health.get_health_report(),
            "metrics": self.metrics.get_all_metrics(),
            "resources": self.resource_monitor.get_usage(),
            "timestamp": iso(utcnow())
        }


class OperationTracker:
    """Context manager for tracking operation metrics."""
    
    def __init__(self, monitoring: MonitoringSystem, operation_name: str):
        self.monitoring = monitoring
        self.operation_name = operation_name
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        self.monitoring.metrics.increment(f"{self.operation_name}.started")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            self.monitoring.metrics.timing(f"{self.operation_name}.duration", duration_ms)
            
            if exc_type is None:
                self.monitoring.metrics.increment(f"{self.operation_name}.success")
            else:
                self.monitoring.metrics.increment(f"{self.operation_name}.failure")
                self.monitoring.logger.error(
                    f"Operation {self.operation_name} failed",
                    error=str(exc_val),
                    duration_ms=round(duration_ms, 2)
                )
        
        return False  # Don't suppress exceptions


# Global monitoring instance
def get_monitoring() -> MonitoringSystem:
    """Get the global monitoring system instance."""
    return MonitoringSystem()


def track_event(event_type: str, message: str, **kwargs):
    """Convenience function to log structured events."""
    monitoring = get_monitoring()
    monitoring.logger.event(event_type, message, **kwargs)


def increment_metric(name: str, value: int = 1, **tags):
    """Convenience function to increment metrics."""
    monitoring = get_monitoring()
    monitoring.metrics.increment(name, value, tags or None)


def record_gauge(name: str, value: float, **tags):
    """Convenience function to set gauge metrics."""
    monitoring = get_monitoring()
    monitoring.metrics.gauge(name, value, tags or None)
