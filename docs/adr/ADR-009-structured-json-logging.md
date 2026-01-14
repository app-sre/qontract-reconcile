# ADR-009: Structured JSON Logging for Production Systems

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

Production systems need machine-readable logs for effective monitoring, debugging, and alerting. Traditional text-based logs are difficult to parse and query in log aggregation systems like Elasticsearch, Splunk, or CloudWatch.

**Current Situation:**

- API services generate thousands of log entries per hour
- Logs need to be searchable by specific fields (request_id, workspace, usergroup, etc.)
- Debugging requires correlating logs across multiple requests and workers
- Different environments have different logging needs (production vs development)

**Problems with Plain Text Logging:**

- **No structured queries:** Can't easily filter by specific fields
- **Regex parsing required:** Fragile and error-prone in log aggregation systems
- **Poor correlation:** Hard to trace all logs for a single request
- **Lost context:** Extra fields (workspace, usergroup, action_type) not easily accessible
- **No metric extraction:** Can't easily extract numeric values (duration, status codes)

**Requirements:**

- Machine-readable JSON logs for production (log aggregation systems)
- Human-readable logs for development (debugging with stacktraces)
- Automatic request tracking across all log entries
- Support for arbitrary extra fields (workspace, usergroup, action_type, etc.)
- Easy to search, filter, and query in log aggregation tools
- No performance impact on request processing

**Constraints:**

- Must work with Python's standard logging library
- Must integrate with FastAPI middleware
- Must support both synchronous and asynchronous code
- Environment variable configuration (no code changes)

## Decision

We adopt **dual-mode structured logging** with JSON format for production and standard format for development.

**Production Mode (JSON):**

- Use `structlog` library for structured JSON output
- Request ID automatically added to every log entry

**Development Mode (Standard):**

- Human-readable logs with timestamps and stacktraces
- Easier debugging with readable output
- Still includes request ID tracking

**Configuration:**

- `QAPI_LOG_FORMAT_JSON=true` (default): JSON logging for production
- `QAPI_LOG_FORMAT_JSON=false`: Standard logging for development

### Key Points

- **Dual-mode logging:** JSON for production, standard for development
- **Automatic request tracking:** Request ID in context variable, added to all logs
- **Extra fields support:** Any extra fields passed to log calls included in JSON
- **Zero code changes:** Switch modes via environment variable
- **Standard library integration:** Uses Python's logging module

## Alternatives Considered

### Alternative 1: Plain Text Logging Only

Use Python's standard logging with text format for all environments.

```python
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
```

**Pros:**

- Simple, no external dependencies
- Easy to read in console
- Works everywhere

**Cons:**

- Not machine-readable (requires regex parsing)
- Hard to query in log aggregation systems
- Can't extract structured fields (duration, status codes)
- Extra fields (workspace, usergroup) lost or buried in message
- No correlation between related log entries

### Alternative 2: Custom Log Format Parser

Use plain text logging with a custom format that can be parsed.

```python
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(request_id)s | %(message)s"
)
# Log aggregation system parses with regex
```

**Pros:**

- No external dependencies
- Somewhat structured

**Cons:**

- Fragile regex parsing required
- Extra fields require format string changes
- Can't handle arbitrary extra fields
- Parsing errors in log aggregation systems
- Still hard to query complex structures

### Alternative 3: Structured JSON Logging (Selected)

Use `structlog` with custom formatter for automatic field inclusion.

```python
# Production (LOG_FORMAT_JSON=true)
{
    "client_host": "172.18.0.3",
    "event": "Start GET /api/v1/external/pagerduty/schedules/PQ022DV/users",
    "http_method": "GET",
    "http_path": "/api/v1/external/pagerduty/schedules/PQ022DV/users",
    "level": "info",
    "request_id": "e3b32fc5-cf4f-4fc2-9fb8-bff4fb4231df",
    "timestamp": "2025-12-11 12:14:24"
}


# Development (LOG_FORMAT_JSON=false)
2025-12-11 12:16:18 [info     ] Start GET /api/v1/external/pagerduty/schedules/PQ022DV/users client_host=172.18.0.5 http_method=GET http_path=/api/v1/external/pagerduty/schedules/PQ022DV/users request_id=993c9e0c-c112-4d70-8aa7-9f6f27dfc7a7
```

**Pros:**

- Machine-readable JSON for log aggregation
- Easy to query by any field
- Automatic extra field inclusion
- Request correlation via request_id
- Switchable between modes (no code changes)
- Excellent tooling support (Elasticsearch, Splunk, etc.)

**Cons:**

- External dependency (`structlog`)
- JSON harder to read in console
  - **Mitigation:** Development mode uses standard format

## Consequences

### Positive

- **Easy log queries:** Filter by any field in log aggregation systems
- **Request tracing:** Every log entry includes request_id automatically
- **Rich context:** Extra fields (workspace, usergroup, action_type) included
- **Flexible querying:** JSON structure enables complex queries
- **Development friendly:** Standard mode for readable debugging
- **No code changes:** Switch modes via environment variable
- **Metric extraction:** Numeric fields (duration, status_code) easily extracted
- **Standard library compatible:** Uses Python's logging module

### Negative

- **External dependency:** Requires `structlog` library
  - **Mitigation:** Well-maintained library (2M+ downloads/month)
  - **Mitigation:** Small dependency footprint

- **JSON harder to read:** Console output less readable in production
  - **Mitigation:** Use development mode for local debugging
  - **Mitigation:** Log aggregation tools format JSON nicely

- **Slightly larger log size:** JSON overhead (field names repeated)
  - **Mitigation:** Negligible impact (~10-20% larger)
  - **Mitigation:** Compression in log aggregation reduces impact

## Implementation Guidelines

### Logger Configuration

Setup logging with dual-mode support. See `qontract_api/logger.py` for implementation details.

### Logging with Extra Fields

Log with arbitrary extra fields:

```python

from qontract_api.logger import get_logger

logger = get_logger(__name__)

logger.info(
    "Reconciling usergroup",
    # just use keyword arguments for extra fields
    workspace=workspace_name,
    usergroup=usergroup_handle,
    action_type="update",
    users_added=3,
    users_removed=1,
)
```

**JSON Output:**

```json
{
  "timestamp": "2025-11-18 10:30:45",
  "level": "INFO",
  "logger": "qontract_api.service",
  "event": "Reconciling usergroup",
  "request_id": "abc-123",
  "workspace": "app-sre",
  "usergroup": "on-call",
  "action_type": "update",
  "users_added": 3,
  "users_removed": 1
}
```

### Environment Configuration

Configure via environment variables:

```bash
# Production: JSON logging
export QAPI_LOG_FORMAT_JSON=true
export QAPI_LOG_LEVEL=INFO

# Development: Standard logging with stacktraces
export QAPI_LOG_FORMAT_JSON=false
export QAPI_LOG_LEVEL=DEBUG
```

### Log Aggregation Queries

Example queries in log aggregation systems:

```javascript
// Elasticsearch: Find all logs for a specific request
{
  "query": {
    "match": { "request_id": "abc-123" }
  }
}

// Find all reconciliation errors for a workspace
{
  "query": {
    "bool": {
      "must": [
        { "match": { "level": "ERROR" }},
        { "match": { "workspace": "app-sre" }}
      ]
    }
  }
}

// Average reconciliation duration by workspace
{
  "aggs": {
    "by_workspace": {
      "terms": { "field": "workspace" },
      "aggs": {
        "avg_duration": { "avg": { "field": "duration_seconds" }}
      }
    }
  }
}
```

## References

- Implementation: `qontract_api/qontract_api/logger.py`
- Middleware: `qontract_api/qontract_api/middleware.py`
- External library: [structlog](http://structlog.org)
- Related patterns: Request ID tracking, Context variables in Python

---

## Notes

**Performance Impact:**

JSON serialization adds minimal overhead (~1-2ms per log entry). In production, this is negligible compared to I/O operations and API calls.

**Example: Request Tracing**

When debugging a failed request:

1. Get request ID from API response header (`X-Request-ID`)
2. Query logs by `request_id` field
3. See ALL logs for that request across all workers
4. Trace execution flow chronologically

This makes debugging multi-worker scenarios trivial.
