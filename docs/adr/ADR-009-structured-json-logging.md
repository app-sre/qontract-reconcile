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

- Use `python-json-logger` library for structured JSON output
- Custom formatter includes all extra fields automatically
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

Use `python-json-logger` with custom formatter for automatic field inclusion.

```python
# Production (LOG_FORMAT_JSON=true)
{
  "timestamp": "2025-11-18 10:30:45",
  "level": "INFO",
  "logger": "qontract_api.service",
  "message": "Reconciling usergroup",
  "request_id": "abc-123",
  "workspace": "app-sre",
  "usergroup": "on-call",
  "duration_seconds": 0.123
}

# Development (LOG_FORMAT_JSON=false)
2025-11-18 10:30:45 - qontract_api.service - INFO - Reconciling usergroup
```

**Pros:**

- Machine-readable JSON for log aggregation
- Easy to query by any field
- Automatic extra field inclusion
- Request correlation via request_id
- Switchable between modes (no code changes)
- Excellent tooling support (Elasticsearch, Splunk, etc.)

**Cons:**

- External dependency (`python-json-logger`)
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

- **External dependency:** Requires `python-json-logger` library
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

Setup logging with dual-mode support:

```python
from pythonjsonlogger.json import JsonFormatter
from qontract_api.config import settings

def setup_logging() -> logging.Logger:
    """Configure logging with JSON or standard format."""
    handler = logging.StreamHandler(sys.stdout)

    if settings.log_format_json:
        # JSON formatter for production
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s"
        )
    else:
        # Standard formatter for development
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler.setFormatter(formatter)
    handler.addFilter(RequestIDFilter())

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    return logging.getLogger("qontract_api")
```

### Custom JSON Formatter

Include all extra fields automatically:

```python
class CustomJsonFormatter(JsonFormatter):
    """Custom JSON formatter with enhanced field mapping."""

    def add_fields(
        self,
        log_record: dict[str, object],
        record: logging.LogRecord,
        message_dict: dict[str, object],
    ) -> None:
        """Add fields to the JSON log record."""
        super().add_fields(log_record, record, message_dict)

        # Standard fields
        log_record["timestamp"] = self.formatTime(record)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["message"] = record.getMessage()

        # Add request_id if available
        if hasattr(record, "request_id") and record.request_id:
            log_record["request_id"] = record.request_id

        # Include all extra fields (workspace, usergroup, etc.)
        excluded_fields = {
            "name", "msg", "args", "created", "filename", ...
        }
        log_record.update({
            key: value
            for key, value in record.__dict__.items()
            if key not in excluded_fields and not key.startswith("_")
        })
```

### Request ID Tracking

Use context variable for automatic request ID injection:

```python
from contextvars import ContextVar

# Context variable for request ID
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

class RequestIDFilter(logging.Filter):
    """Add request_id to all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Set request ID in context for each request."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        token = request_id_context.set(request_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context.reset(token)
```

### Logging with Extra Fields

Log with arbitrary extra fields:

```python
logger.info(
    "Reconciling usergroup",
    extra={
        "workspace": workspace_name,
        "usergroup": usergroup_handle,
        "action_type": "update",
        "users_added": 3,
        "users_removed": 1,
    }
)
```

**JSON Output:**

```json
{
  "timestamp": "2025-11-18 10:30:45",
  "level": "INFO",
  "logger": "qontract_api.service",
  "message": "Reconciling usergroup",
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
- External library: [python-json-logger](https://github.com/madzak/python-json-logger)
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
