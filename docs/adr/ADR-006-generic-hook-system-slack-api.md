# ADR-006: Generic Hook System for API Wrappers

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

API wrappers (Slack, GitHub, GitLab, AWS, etc.) need to support multiple cross-cutting concerns:

- **Prometheus metrics**: Track all API calls with method/verb/service labels
- **Rate limiting**: Enforce rate limits before API calls
- **Logging**: Debug/trace API calls with context
- **Tracing**: Distributed tracing with OpenTelemetry (future)
- **Authentication**: Token refresh, credential rotation (future)

### Problem Without Hook System

**Before (SlackApi initial implementation)**:

```python
def chat_post_message(self, text: str) -> None:
    # Manual metric tracking in EVERY method
    slack_request.labels("chat.postMessage", "POST").inc()
    self._sc.chat_postMessage(channel=self.channel, text=text, **self.chat_kwargs)
```

**Issues:**

- Manual metrics in every API method (9 duplicate calls across SlackApi)
- No way to inject rate limiting or logging
- Adding new concerns requires modifying every method
- Code duplication across different API wrappers
- No context information for cross-cutting concerns

## Decision

**Implement generic hook system with service-specific context objects for all API wrappers.**

### Pattern

All API wrappers should follow this pattern:

**1. Service-Specific Context Dataclass** (frozen, immutable):

```python
@dataclass(frozen=True)
class SlackApiCallContext:
    method: str      # e.g., "chat.postMessage"
    verb: str        # e.g., "GET", "POST"
    workspace: str   # Service-specific field
```

**2. Hook Signature**: `Callable[[<Service>ApiCallContext], None]`

**3. Multiple Hooks Support**:

```python
before_api_call_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None
```

**4. Built-in Hooks** (always included):

```python
def _metrics_hook(context: SlackApiCallContext) -> None:
    """Built-in hook for Prometheus metrics."""
    slack_request.labels(context.method, context.verb).inc()
```

**5. Hook Execution**:

```python
def _call_hooks(self, method: str, verb: str) -> None:
    context = SlackApiCallContext(method=method, verb=verb, workspace=self.workspace_name)
    for hook in self._before_api_call_hooks:
        hook(context)
```

## Implementation Example: SlackApi

### Complete Implementation

```python
from dataclasses import dataclass
from collections.abc import Callable, Sequence

@dataclass(frozen=True)
class SlackApiCallContext:
    """Context for Slack API calls."""
    method: str
    verb: str
    workspace: str

def _metrics_hook(context: SlackApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    slack_request.labels(context.method, context.verb).inc()

class SlackApi:
    def __init__(
        self,
        workspace_name: str,
        token: str,
        before_api_call_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None = None,
        *,
        init_usergroups: bool = True,
        channel: str | None = None,
        **chat_kwargs: Any,
    ) -> None:
        # Always include metrics hook first, then user hooks
        self._before_api_call_hooks = [_metrics_hook]
        if before_api_call_hooks:
            self._before_api_call_hooks.extend(before_api_call_hooks)

    def _call_hooks(self, method: str, verb: str) -> None:
        context = SlackApiCallContext(method=method, verb=verb, workspace=self.workspace_name)
        for hook in self._before_api_call_hooks:
            hook(context)

    def chat_post_message(self, text: str) -> None:
        self._call_hooks("chat.postMessage", "POST")  # Automatic metrics + user hooks!
        self._sc.chat_postMessage(channel=self.channel, text=text, **self.chat_kwargs)
```

### Factory Pattern with Rate Limiting Hook

```python
def create_slack_api(workspace_name: str, token: str, cache: CacheBackend, settings: Settings) -> SlackApi:
    token_bucket = TokenBucket(cache=cache, bucket_name=f"slack:{workspace_name}", ...)

    def rate_limit_hook(_context: SlackApiCallContext) -> None:
        token_bucket.acquire(tokens=1, timeout=30)

    # Metrics hook automatically included
    return SlackApi(
        workspace_name,
        token,
        before_api_call_hooks=[rate_limit_hook],
        init_usergroups=True,
    )
```

### Multiple Hooks Composition Example

Real-world scenario demonstrating composition of multiple hooks for comprehensive observability:

```python
from qontract_api.logger import get_logger

logger = get_logger(__name__)

def create_slack_api_with_full_observability(
    workspace_name: str,
    token: str,
    cache: CacheBackend,
    settings: Settings,
) -> SlackApi:
    """Create SlackApi with rate limiting, logging, and tracing hooks.

    Demonstrates hook composition for production observability:
    - Rate limiting prevents API quota exhaustion
    - Structured logging provides debug context
    - Tracing hook prepared for OpenTelemetry integration
    """
    # Hook 1: Rate limiting (token bucket)
    bucket_name = f"slack:{settings.SLACK_RATE_LIMIT_TIER}:{workspace_name}"
    token_bucket = TokenBucket(
        cache=cache,
        bucket_name=bucket_name,
        capacity=settings.SLACK_RATE_LIMIT_TOKENS,
        refill_rate=settings.SLACK_RATE_LIMIT_REFILL_RATE,
    )

    def rate_limit_hook(_context: SlackApiCallContext) -> None:
        """Acquire rate limit token before API call."""
        token_bucket.acquire(tokens=1, timeout=30)

    # Hook 2: Structured logging
    def logging_hook(context: SlackApiCallContext) -> None:
        """Log API call details for debugging."""
        logger.debug(
            "Slack API call",
            method=context.method,
            verb=context.verb,
            workspace=context.workspace,
        )

    # Hook 3: Distributed tracing (prepared for future)
    def tracing_hook(context: SlackApiCallContext) -> None:
        """Create tracing span (placeholder for OpenTelemetry integration)."""
        # Future: tracer.start_span(f"slack.{context.method}")
        pass

    # Metrics hook automatically included first, then user hooks in order
    return SlackApi(
        workspace_name,
        token,
        before_api_call_hooks=[
            rate_limit_hook,    # Executed 2nd (after built-in metrics)
            logging_hook,       # Executed 3rd
            tracing_hook,       # Executed 4th
        ],
        init_usergroups=True,
    )
```

**Hook Execution Order:**

1. **Built-in `_metrics_hook`** (always first) - Prometheus metrics
2. **`rate_limit_hook`** - Blocks if rate limit exceeded
3. **`logging_hook`** - Logs API call details
4. **`tracing_hook`** - Creates tracing span (future)
5. **Actual API call** - `slack_client.chat_postMessage(...)`

**Key Points:**

- Hooks execute sequentially in order
- If any hook raises exception, API call is aborted
- Built-in metrics hook always runs first
- User hooks run in list order (composable and predictable)

## Future Enhancements

The current implementation focuses on `before_api_call_hooks`. Future versions could support additional hook types for comprehensive API lifecycle management.

### Other Possible Hook Types

#### 1. `after_api_call_hooks`

Execute hooks after successful API calls.

**Signature:**

```python
Callable[[<Service>ApiCallContext, Response], None]
```

**Use Cases:**

- **Response caching**: Cache API responses for performance
- **Success metrics**: Track successful API call latency, response sizes
- **Audit logging**: Log successful operations with response data
- **Webhooks**: Trigger notifications on successful operations

**Example:**

```python
def cache_response_hook(context: SlackApiCallContext, response: Any) -> None:
    """Cache successful API responses."""
    cache_key = f"slack:{context.workspace}:{context.method}"
    cache.set(cache_key, response, ttl=300)

def success_metrics_hook(context: SlackApiCallContext, response: Any) -> None:
    """Track successful API call metrics."""
    slack_success.labels(context.method, context.workspace).inc()

SlackApi(
    workspace_name,
    token,
    after_api_call_hooks=[cache_response_hook, success_metrics_hook],
)
```

#### 2. `on_error_hooks`

Execute hooks when API calls fail with exceptions.

**Signature:**

```python
Callable[[<Service>ApiCallContext, Exception], None]
```

**Use Cases:**

- **Error metrics**: Track API failure rates by error type
- **Alerting**: Send alerts on critical errors
- **Error logging**: Log detailed error context for debugging
- **Retry decision logic**: Decide whether to retry based on error type

**Example:**

```python
def error_metrics_hook(context: SlackApiCallContext, error: Exception) -> None:
    """Track API error metrics by type."""
    error_type = type(error).__name__
    slack_errors.labels(context.method, error_type, context.workspace).inc()

def alert_on_auth_error_hook(context: SlackApiCallContext, error: Exception) -> None:
    """Alert on authentication failures."""
    if isinstance(error, SlackApiError) and error.response.get("error") == "invalid_auth":
        alertmanager.send_alert(
            severity="critical",
            summary=f"Slack auth failed for workspace {context.workspace}",
        )

SlackApi(
    workspace_name,
    token,
    on_error_hooks=[error_metrics_hook, alert_on_auth_error_hook],
)
```

#### 3. `on_retry_hooks`

Execute hooks before each retry attempt.

**Signature:**

```python
Callable[[<Service>ApiCallContext, int], None]  # retry_attempt number
```

**Use Cases:**

- **Retry metrics**: Track retry attempts and backoff behavior
- **Retry logging**: Log retry attempts with context
- **Dynamic backoff**: Adjust backoff strategy based on error patterns
- **Circuit breaker**: Open circuit after N consecutive retries

**Example:**

```python
def retry_metrics_hook(context: SlackApiCallContext, retry_attempt: int) -> None:
    """Track retry attempts."""
    slack_retries.labels(context.method, context.workspace).inc()
    logger.warning(
        "Retrying Slack API call",
        method=context.method,
        workspace=context.workspace,
        retry_attempt=retry_attempt,
    )

SlackApi(
    workspace_name,
    token,
    on_retry_hooks=[retry_metrics_hook],
)
```

#### 4. `on_timeout_hooks`

Execute hooks when API calls timeout.

**Signature:**

```python
Callable[[<Service>ApiCallContext, float], None]  # timeout_duration in seconds
```

**Use Cases:**

- **Timeout metrics**: Track timeout rates by endpoint
- **Circuit breaker**: Open circuit after timeout threshold
- **Adaptive timeouts**: Adjust timeouts based on historical latency
- **Alerting**: Alert on high timeout rates

**Example:**

```python
def timeout_metrics_hook(context: SlackApiCallContext, timeout_duration: float) -> None:
    """Track API call timeouts."""
    slack_timeouts.labels(context.method, context.workspace).inc()
    logger.error(
        "Slack API call timed out",
        method=context.method,
        workspace=context.workspace,
        timeout_duration=timeout_duration,
    )

SlackApi(
    workspace_name,
    token,
    on_timeout_hooks=[timeout_metrics_hook],
)
```

### Backward Compatibility

New hook types will be introduced as **optional parameters** to maintain backward compatibility:

```python
class SlackApi:
    def __init__(
        self,
        workspace_name: str,
        token: str,
        before_api_call_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None = None,
        after_api_call_hooks: Sequence[Callable[[SlackApiCallContext, Any], None]] | None = None,  # New
        on_error_hooks: Sequence[Callable[[SlackApiCallContext, Exception], None]] | None = None,  # New
        on_retry_hooks: Sequence[Callable[[SlackApiCallContext, int], None]] | None = None,  # New
        on_timeout_hooks: Sequence[Callable[[SlackApiCallContext, float], None]] | None = None,  # New
        **kwargs: Any,
    ) -> None:
        ...
```

**Migration Path:**

1. Existing code using `before_api_call_hooks` continues to work unchanged
2. New hook types are opt-in (default: `None`)
3. Services can adopt new hooks incrementally
4. No breaking changes to existing API wrappers

### Implementation Timeline

- **Phase 1 (Current)**: `before_api_call_hooks` - Rate limiting, logging, tracing
- **Phase 2 (Next)**: `after_api_call_hooks` - Response caching, success metrics
- **Phase 3 (Future)**: `on_error_hooks` - Error handling, alerting
- **Phase 4 (Future)**: `on_retry_hooks`, `on_timeout_hooks` - Advanced resilience patterns

## Alternatives Considered

### Alternative 1: Manual Implementation (Rejected)

Each API wrapper manually implements metrics, logging, rate limiting.

**Cons:**

- Code duplication across services
- Inconsistent implementation
- Hard to maintain
- Not reusable

### Alternative 2: Decorator Pattern (Rejected)

```python
@track_metrics
@rate_limit
def chat_post_message(self, text: str) -> None:
    self._sc.chat_postMessage(...)
```

**Cons:**

- Decorators can't access runtime context (workspace, method name)
- Hard to pass configuration dynamically
- Order of decorators matters
- Doesn't work well with dynamic hook registration

### Alternative 3: Generic Hook System (Selected)

Service-specific context dataclasses with multiple hook support.

**Pros:**

- Reusable pattern across all services
- Context-aware hooks
- Type-safe with dataclasses
- Simple to implement
- Extensible without code changes

## Consequences

### Positive

1. **Reusable pattern**: All API wrappers follow same pattern
2. **Code reduction**: Eliminates manual metrics in every API method
3. **Extensibility**: New hooks without modifying API wrapper
4. **Maintainability**: Changes to hooks don't touch every API method
5. **Testability**: Hooks can be tested independently
6. **Consistency**: Standardized approach across all services
7. **Type safety**: Service-specific contexts catch errors at compile time

### Negative

1. **Learning curve**: Developers need to understand the hook pattern
   - **Mitigation:** Well-documented with examples for each service
   - Industry-standard pattern (similar to HTTP middleware)

2. **Slight overhead**: Hook execution loop adds minimal overhead
   - **Mitigation:** Negligible compared to network latency of API calls

3. **Context design**: Each service needs its own context dataclass
   - **Mitigation:** Clear pattern to follow (method, verb, service-specific fields)

## Implementation Guidelines

### For New API Wrappers

1. **Define service-specific context** (frozen dataclass with `method`, `verb`, + service fields)
2. **Create built-in metrics hook** (track API calls with service-specific labels)
3. **Accept hook list in `__init__`**: `before_api_call_hooks: Sequence[Callable[[...], None]] | None`
4. **Always include metrics hook first**, then extend with user hooks
5. **Implement `_call_hooks` method** (create context, execute all hooks)
6. **Call hooks before API calls**: `self._call_hooks(method, verb)` in every API method

### Hook Development Guidelines

1. **Hook signature**: `def hook(context: <Service>ApiCallContext) -> None`
2. **No return value**: Hooks perform side effects only
3. **Error handling**: If hook raises exception, API call fails
4. **Unused context**: Use `_` prefix if context not needed (`_context`)

## References

- Implementation: [SlackApi](../../../qontract_utils/qontract_utils/slack_api.py), [Factory](../../qontract_api/integrations/slack_usergroups/slack_factory.py)
- Related: [ADR-004](ADR-004-centralized-rate-limiting-via-hooks.md) - Centralized Rate Limiting (uses hook system)
- External: [Middleware pattern](https://en.wikipedia.org/wiki/Middleware), [Hook pattern](https://en.wikipedia.org/wiki/Hooking)
