# Multi-Agent System Improvements for SocialBot

## Overview

This document describes the comprehensive improvements made to SocialBot to support multiple concurrent agents, enhanced monitoring, and robust coordination.

## New Modules

### 1. `agents.py` - Multi-Agent Coordination

**Purpose**: Coordinates multiple agents running concurrently across different processes/machines.

**Key Features**:
- **Agent Registration & Tracking**: Each agent registers with a unique ID and sends periodic heartbeats
- **Distributed Locking**: SQLite-based locks prevent race conditions during critical operations
- **Task Queue**: Priority-based task distribution across agents
- **Dead Agent Detection**: Automatically detects and cleans up dead agents (no heartbeat within 90s)
- **Load Balancing**: Tasks are distributed based on availability and priority

**Usage**:
```python
from socialbot.agents import get_coordinator, distributed_lock

# Get global coordinator (auto-registers agent)
coordinator = get_coordinator()

# Use distributed lock for critical sections
with distributed_lock("publish_post_123"):
    # Only one agent can execute this at a time
    perform_publish()

# Enqueue tasks for processing
task_id = coordinator.enqueue_task(
    task_type="publish",
    payload={"post_id": "123"},
    priority=5
)

# Claim and process tasks
task = coordinator.claim_task(task_types=["publish"])
if task:
    process_task(task)
    coordinator.complete_task(task.task_id, {"result": "success"})
```

**Database Tables Added**:
- `agents`: Tracks registered agents and their status
- `locks`: Distributed lock management
- `task_queue`: Priority-based task queue with retry support

### 2. `monitoring.py` - Enhanced Monitoring & Metrics

**Purpose**: Provides comprehensive monitoring, metrics collection, and structured logging.

**Key Components**:

#### MetricsCollector
- **Counters**: Track cumulative events (e.g., publishes started, completed)
- **Gauges**: Current values (e.g., active platforms, queue size)
- **Timings**: Operation durations in milliseconds

#### HealthChecker
- Database connectivity checks
- Resource usage monitoring
- Process health verification
- Custom health check registration

#### StructuredLogger
- JSON-formatted log output
- Event tracking with metadata
- Contextual information in every log entry

#### ResourceMonitor
- CPU usage tracking
- Memory consumption (RSS, percentage)
- Thread count, open files, connections
- Threshold-based alerting

**Usage**:
```python
from socialbot.monitoring import (
    get_monitoring, 
    track_event, 
    increment_metric, 
    record_gauge
)

monitoring = get_monitoring()

# Track operation timing
with monitoring.track_operation("publish"):
    perform_publish()

# Log structured events
track_event("publish.success", "Post published successfully", 
           post_id="123", platform="twitter")

# Record metrics
increment_metric("publish.count", tags={"platform": "twitter"})
record_gauge("queue.size", 15)

# Get health status
health_report = monitoring.health.get_health_report()
metrics = monitoring.metrics.get_all_metrics()
```

### 3. Enhanced `publisher.py`

**Improvements**:
- Integrated distributed locking for safe multi-agent publishing
- Comprehensive metrics tracking for all operations
- Structured event logging
- Per-platform timing measurements
- Error categorization and tracking

**Metrics Tracked**:
- `publish.started`: Count of publish operations initiated
- `publish.platform.success`: Successful platform publishes (tagged by platform)
- `publish.platform.failure`: Failed platform publishes
- `publish.platform.error`: Unexpected errors (tagged by error type)
- `publish.completed.success/partial/failed`: Final outcome counts
- `publish.duration.{platform}`: Time per platform in ms
- `process_due.checked/published/failed`: Scheduler processing stats

### 4. Enhanced API Endpoints (`api/app.py`)

**New Endpoints**:

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Basic health check (existing, enhanced) |
| `GET /api/health/detailed` | Comprehensive health status with all components |
| `GET /api/agents/stats` | Multi-agent coordination statistics |
| `GET /api/agents/list` | List all registered agents |
| `GET /api/tasks` | View task queue (filterable by status) |
| `GET /api/metrics` | Current performance metrics |

**Example Responses**:

`/api/health/detailed`:
```json
{
  "health": {
    "overall_status": "healthy",
    "components": {
      "database": {
        "component": "database",
        "status": "healthy",
        "message": "Database responsive (2.3ms)",
        "latency_ms": 2.3
      },
      "resources": {
        "component": "resources",
        "status": "healthy",
        "message": "Resources within normal range"
      }
    }
  },
  "metrics": {
    "counters": {
      "publish.started": 42,
      "publish.completed.success": 38
    },
    "gauges": {
      "publish.total_platforms": 5.0
    }
  },
  "timestamp": "2026-08-19T18:12:22.139+00:00"
}
```

`/api/agents/stats`:
```json
{
  "active_agents": 3,
  "pending_tasks": 5,
  "claimed_tasks": 2,
  "completed_today": 127,
  "failed_today": 3,
  "timestamp": "2026-08-19T18:12:22.139+00:00"
}
```

## Architecture

### Multi-Agent Setup

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Agent 1       │     │   Agent 2       │     │   Agent 3       │
│  (Publisher)    │     │  (Scheduler)    │     │  (Bot Engine)   │
│                 │     │                 │     │                 │
│ ┌─────────────┐ │     │ ┌─────────────┐ │     │ ┌─────────────┐ │
│ │ Coordinator │ │     │ │ Coordinator │ │     │ │ Coordinator │ │
│ └─────────────┘ │     │ └─────────────┘ │     │ └─────────────┘ │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   SQLite Database       │
                    │                         │
                    │ - posts                 │
                    │ - accounts              │
                    │ - agents (NEW)          │
                    │ - locks (NEW)           │
                    │ - task_queue (NEW)      │
                    └─────────────────────────┘
```

### Task Flow

1. **Task Creation**: API request or scheduler creates task
2. **Queue Assignment**: Task added to `task_queue` with priority
3. **Agent Claim**: Available agents poll for pending tasks
4. **Lock Acquisition**: Agent acquires distributed lock if needed
5. **Task Execution**: Agent performs the work
6. **Completion**: Agent marks task complete/fail and releases lock
7. **Retry Logic**: Failed tasks automatically requeued (up to max_retries)

### Dead Agent Handling

```
Agent stops sending heartbeats
         │
         ▼
90 seconds timeout expires
         │
         ▼
Another agent's cleanup detects it
         │
         ▼
Status changed to 'dead'
         │
         ├─► Locks released
         │
         └─► Claimed tasks returned to pending
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_ID` | Auto-generated | Unique agent identifier |
| `HOSTNAME` | "unknown" | Agent hostname for tracking |
| `SOCIALBOT_DB` | "socialbot.db" | Path to SQLite database |

### Tuning Parameters

In `agents.py`:
```python
DEFAULT_AGENT_HEARTBEAT_INTERVAL = 30  # seconds between heartbeats
DEFAULT_AGENT_TIMEOUT = 90  # seconds without heartbeat = dead
DEFAULT_LOCK_TIMEOUT = 30  # seconds before lock expires
```

In `monitoring.py`:
```python
# Resource alerting thresholds
cpu_threshold = 90.0  # percent
memory_threshold = 90.0  # percent
```

## Running Multiple Agents

### Scenario 1: Multiple Processes on Same Machine

```bash
# Terminal 1 - Publisher agent
AGENT_ID=publisher_1 python -m socialbot api --port 8000

# Terminal 2 - Scheduler agent  
AGENT_ID=scheduler_1 python -m socialbot scheduler

# Terminal 3 - Bot engine agent
AGENT_ID=bot_1 python -m socialbot bot run-all
```

### Scenario 2: Distributed Across Machines

```bash
# Machine 1
export AGENT_ID=prod_publisher_1
export SOCIALBOT_DB=/shared/socialbot.db
python -m socialbot api --port 8000

# Machine 2
export AGENT_ID=prod_publisher_2
export SOCIALBOT_DB=/shared/socialbot.db
python -m socialbot api --port 8000

# Machine 3
export AGENT_ID=prod_scheduler_1
export SOCIALBOT_DB=/shared/socialbot.db
python -m socialbot scheduler
```

**Note**: For distributed setups, ensure the database file is on shared storage accessible to all agents.

## Monitoring Dashboard Integration

The new endpoints integrate with existing dashboard:

```javascript
// Fetch agent stats
fetch('/api/agents/stats')
  .then(r => r.json())
  .then(stats => {
    document.getElementById('active-agents').textContent = stats.active_agents;
    document.getElementById('pending-tasks').textContent = stats.pending_tasks;
  });

// Fetch detailed health
fetch('/api/health/detailed')
  .then(r => r.json())
  .then(health => {
    // Display component statuses
  });
```

## Best Practices

### 1. Always Use Distributed Locks for Critical Sections
```python
# Good - prevents duplicate publishes
with distributed_lock(f"publish_{post_id}"):
    publisher.publish_now(post)

# Bad - race condition possible
publisher.publish_now(post)
```

### 2. Monitor Agent Health
```python
# Check for dead agents periodically
dead_agents = coordinator.cleanup_dead_agents()
if dead_agents:
    log.warning("Dead agents detected: %s", dead_agents)
```

### 3. Use Task Queue for Long Operations
```python
# Instead of blocking API call
task_id = coordinator.enqueue_task(
    "bulk_publish",
    {"post_ids": ids},
    priority=5
)
return {"task_id": task_id, "status": "queued"}
```

### 4. Tag Metrics Appropriately
```python
# Good - enables filtering
increment_metric("publish.error", tags={
    "platform": "twitter",
    "error_type": "RateLimit"
})

# Bad - no context
increment_metric("publish.error")
```

## Migration Guide

### Existing Single-Agent Deployments

No breaking changes! The system works in single-agent mode by default:
- Coordinator initializes but doesn't interfere
- Locks are acquired/released immediately
- Task queue remains empty unless explicitly used

### Enabling Multi-Agent Features

1. **Add Agent IDs**: Set unique `AGENT_ID` for each process
2. **Shared Database**: Ensure all agents use same `SOCIALBOT_DB`
3. **Update Monitoring**: Add new endpoints to your monitoring stack
4. **Configure Alerts**: Set up alerts for dead agents, high error rates

## Troubleshooting

### Agents Not Appearing
- Check `AGENT_ID` is unique per agent
- Verify database path is accessible
- Check logs for registration errors

### Tasks Stuck in "claimed" Status
- Agent may have crashed - wait for timeout (90s)
- Manually reset: `UPDATE task_queue SET status='pending' WHERE status='claimed'`
- Increase heartbeat frequency if timeouts are too aggressive

### Lock Contention
- Reduce lock scope where possible
- Increase `DEFAULT_LOCK_TIMEOUT` for long operations
- Consider operation-specific timeouts

### High Memory Usage
- Check `ResourceMonitor` metrics
- Review `max_points_per_metric` setting
- Enable memory profiling for specific agents

## Future Enhancements

- [ ] Redis-backed coordination for true distributed setup
- [ ] WebSocket real-time updates for dashboard
- [ ] Advanced load balancing algorithms
- [ ] Agent auto-scaling based on queue depth
- [ ] Prometheus/Grafana integration
- [ ] Distributed tracing support

## Testing

Run the test suite:
```bash
python -m pytest tests/test_agents.py
python -m pytest tests/test_monitoring.py
```

Manual testing:
```bash
# Test agent coordination
python -c "from socialbot.agents import *; c = get_coordinator(); print(c.get_agent_stats())"

# Test monitoring
python -c "from socialbot.monitoring import *; m = get_monitoring(); print(m.get_full_status())"

# Test API endpoints
curl http://localhost:8000/api/health/detailed
curl http://localhost:8000/api/agents/stats
```
