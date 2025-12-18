---
name: logging-observability
description: |
  Logging, structured logging, log levels, observability, tracing,
  metrics, monitoring, APM, log aggregation, debugging production,
  correlation IDs, log analysis, alerting.

  Trigger phrases: logging, log level, structured log, observability,
  tracing, metrics, monitoring, APM, log aggregation, production debugging,
  correlation ID, log analysis, alerting, debug logs, info logs,
  error logs, warn logs, log format, log rotation.
---

# Logging & Observability

Tools for logging and system observability.

## Primary Tools

### log-analyzer Agent
```bash
Task(subagent_type="log-analyzer", prompt="Analyze logs in <path>")
```
Parses logs, finds error patterns, correlates events.

## Log Levels

| Level | Use For |
|-------|---------|
| ERROR | Failures requiring attention |
| WARN | Potential issues, degraded state |
| INFO | Normal operations, milestones |
| DEBUG | Detailed troubleshooting info |

## Structured Logging

### JavaScript (pino)
```javascript
import pino from 'pino';

const logger = pino({ level: 'info' });

logger.info({ userId: 123, action: 'login' }, 'User logged in');
// Output: {"level":30,"time":1234567890,"userId":123,"action":"login","msg":"User logged in"}
```

### Python (structlog)
```python
import structlog

logger = structlog.get_logger()

logger.info("user_login", user_id=123, action="login")
# Output: {"event": "user_login", "user_id": 123, "action": "login"}
```

## Correlation IDs

```javascript
// Middleware to add correlation ID
app.use((req, res, next) => {
  req.correlationId = req.headers['x-correlation-id'] || uuid();
  res.setHeader('x-correlation-id', req.correlationId);
  next();
});

// Include in all logs
logger.info({ correlationId: req.correlationId, ... }, 'Request received');
```

## Log Analysis

### Common Patterns
```bash
# Find errors
grep -i "error\|exception\|failed" app.log

# Count by level
grep -oE '"level":"[^"]+"' app.log | sort | uniq -c

# Filter by time range
grep "2024-01-15T1[0-2]:" app.log

# Follow live logs
tail -f app.log | jq 'select(.level == "error")'
```

## Metrics

### Types
- **Counter**: Total count (requests, errors)
- **Gauge**: Current value (connections, memory)
- **Histogram**: Distribution (response times)

### Example (Prometheus)
```javascript
const requestCounter = new Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  labelNames: ['method', 'path', 'status']
});

requestCounter.inc({ method: 'GET', path: '/users', status: 200 });
```

## Distributed Tracing

```javascript
// Create span for operation
const span = tracer.startSpan('db.query');
try {
  const result = await db.query(sql);
  span.setTag('rows', result.length);
  return result;
} catch (error) {
  span.setTag('error', true);
  throw error;
} finally {
  span.finish();
}
```

## Best Practices

### DO
- Use structured logging (JSON)
- Include correlation IDs
- Log at appropriate levels
- Include relevant context
- Rotate logs to prevent disk fill

### DON'T
- Log sensitive data (passwords, tokens)
- Log too verbosely in production
- Use console.log in production
- Ignore log aggregation for distributed systems
