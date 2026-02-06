# ADR-006: Generic Hook System for API Wrappers

**Status:** Accepted
**Date:** 2026-02-06
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
pre_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None
post_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None
error_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None
```

**4. Built-in Hooks** (always included):

```python
def _metrics_hook(context: SlackApiCallContext) -> None:
    """Built-in hook for Prometheus metrics."""
    slack_request.labels(context.method, context.verb).inc()
```

**5. Hook Execution (Method Decorator)**:

```python
@invoke_with_hooks(
    lambda self: SlackApiCallContext(
        method="chat.postMessage",
        verb="POST",
        workspace=self.workspace_name
    )
)
def chat_post_message(self, text: str) -> None:
    self._sc.chat_postMessage(channel=self.channel, text=text, **self.chat_kwargs)
```

## Implementation Example: SlackApi

### Complete Implementation

```python
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, RetryConfig, invoke_with_hooks

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
        pre_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None = None,
        post_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None = None,
        error_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None = None,
        retry_hooks: Sequence[Callable[[SlackApiCallContext, int], None]] | None = None,
        retry_config: RetryConfig | None = DEFAULT_RETRY_CONFIG,
        *,
        init_usergroups: bool = True,
        channel: str | None = None,
        **chat_kwargs: Any,
    ) -> None:
        # Always include metrics hook first, then user hooks
        self._pre_hooks = [_metrics_hook]
        if pre_hooks:
            self._pre_hooks.extend(pre_hooks)
        self._post_hooks: list[Callable[[SlackApiCallContext], None]] = []
        if post_hooks:
            self._post_hooks.extend(post_hooks)
        self._error_hooks: list[Callable[[SlackApiCallContext], None]] = []
        if error_hooks:
            self._error_hooks.extend(error_hooks)
        self._retry_hooks: list[Callable[[SlackApiCallContext, int], None]] = []
        if retry_hooks:
            self._retry_hooks.extend(retry_hooks)
        self._retry_config = retry_config

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="chat.postMessage",
            verb="POST",
            workspace=self.workspace_name
        )
    )
    def chat_post_message(self, text: str) -> None:
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
        pre_hooks=[rate_limit_hook],
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
        pre_hooks=[
            rate_limit_hook,    # Executed 2nd (after built-in metrics)
            logging_hook,       # Executed 3rd
            tracing_hook,       # Executed 4th
        ],
        post_hooks=[post_api_call_hook], # Executed after successful API calls
        error_hooks=[error_handling_hook], # Executed on API call errors
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

## Retry System

The hook system supports automatic retries with exponential backoff using the stamina library.

### RetryConfig

Configuration for retry behavior with stamina-compatible parameters:

```python
from qontract_utils.hooks import NO_RETRY_CONFIG, RetryConfig
from slack_sdk.errors import SlackApiError

# Retry on HTTP errors up to 5 times with 30s timeout
retry_config = RetryConfig(
    on=(SlackApiError, TimeoutError),  # Exception types to retry
    attempts=5,                         # Max 5 attempts
    timeout=30.0,                       # Max 30 seconds total
    wait_initial=0.5,                   # Start with 0.5s wait
    wait_max=10.0,                      # Max 10s between retries
    wait_jitter=2.0,                    # Add up to 2s jitter
    wait_exp_base=2,                    # Exponential backoff base
)
```

**Parameters** (matching `stamina.retry()`):

- `on`: Exception type(s) to retry on, or Callable for custom backoff (**required**)
  - `type[Exception] | tuple[type[Exception], ...]` - Retry on these exception types
  - `Callable[[Exception], bool | float | timedelta]` - Custom decision function
- `attempts`: Max retry attempts (default: 10)
- `timeout`: Max total time in seconds (default: 45.0)
- `wait_initial`: Initial wait in seconds (default: 0.1)
- `wait_max`: Max wait between retries (default: 5.0)
- `wait_jitter`: Jitter in seconds (default: 1.0)
- `wait_exp_base`: Exponential backoff base (default: 2)

### Retry Hooks

Retry hooks are called **before each retry attempt** (attempts 2..N, not the first attempt).

**Signature:**

```python
Callable[[<Service>ApiCallContext, int], None]  # context, retry_attempt_number
```

**Use Cases:**

- Circuit Breaker Pattern
- Custom Alerting for excessive retries
- Context-specific cleanup before retry
- Adaptive request throttling

**Example - Circuit Breaker:**

```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5):
        self.failure_count = 0
        self.threshold = failure_threshold
        self.is_open = False

    def retry_hook(self, context: SlackApiCallContext, retry_attempt: int) -> None:
        """Open circuit breaker after threshold retries."""
        self.failure_count += 1
        if self.failure_count >= self.threshold:
            self.is_open = True
            logger.error(
                "Circuit breaker opened",
                method=context.method,
                workspace=context.workspace,
                failures=self.failure_count,
            )
            raise CircuitBreakerOpenError("Too many failures")

breaker = CircuitBreaker()
api = SlackApi(
    workspace_name="app-sre",
    token=token,
    retry_config=RetryConfig(on=SlackApiError, attempts=5),
    retry_hooks=[breaker.retry_hook],
)
```

### Hook Execution Order with Retry

**Overall flow:**

```
1. Pre-hooks (BEFORE retry_context, once)
   ↓
2. TRY: stamina.retry_context
   ├─ Attempt 1: API Call
   ├─ Attempt 2: retry_hooks(2) → API Call
   ├─ Attempt N: retry_hooks(N) → API Call
   ↓
3a. SUCCESS: finally → Post-hooks
3b. FAILURE (all retries exhausted):
    except → Error hooks → finally → Post-hooks → Exception re-raise
```

**Detailed hook execution:**

1. **Pre-hooks** (once, before retry_context)
   - Metrics counter increment
   - Rate limiting check
   - Initial request logging

2. **Retry Context** (stamina)
   - Attempt 1: Direct API call
   - Attempt 2..N: **Retry hooks** (with attempt number) → API call

3. **Error hooks** (only on final failure, after retry_context)
   - Called ONLY when all retries are exhausted
   - In except-block after retry_context

4. **Post-hooks** (always, after retry_context)
   - In finally-block (runs on success AND failure)
   - Latency recording
   - Cleanup operations

**Important:**

- Pre-hooks: Once BEFORE retry_context
- Retry hooks: Before each retry (attempt 2..N) WITHIN retry_context
- Error hooks: AFTER retry_context only on final failure (except)
- Post-hooks: AFTER retry_context always (finally)
- Exponential backoff with jitter (stamina library)
- stamina tracks retries automatically (structlog + prometheus_client)

### Default Behavior

**Option 1: retry_config=DEFAULT_RETRY_CONFIG (Default stamina behavior)**

- Import: `from qontract_utils.hooks import DEFAULT_RETRY_CONFIG`
- Uses stamina.retry defaults: attempts=10, timeout=45.0, etc.
- API call retried up to 10 times

**Option 2: retry_config=None (Explicit no retry)**

- API call runs exactly once (attempts=1)
- For critical operations that should not be retried

### SlackApi with Retry Support

```python
from qontract_utils.slack_api import SlackApi
from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, RetryConfig
from slack_sdk.errors import SlackApiError

# Example 1: With retry (custom config)
retry_config = RetryConfig(
    on=SlackApiError,
    attempts=5,
    timeout=30.0,
    wait_initial=0.5,
    wait_max=10.0,
)

api_with_retry = SlackApi(
    workspace_name="app-sre",
    token=token,
    retry_config=retry_config,
)

# Example 2: Without retry (explicit)
api_no_retry = SlackApi(
    workspace_name="app-sre",
    token=token,
    retry_config=None,  # Explicit: no retries
)

# Example 3: Default behavior (stamina defaults: attempts=10, timeout=45s)
api_default = SlackApi(
    workspace_name="app-sre",
    token=token,
    retry_config=DEFAULT_RETRY_CONFIG,  # Uses stamina defaults
)
```

## Future Enhancements

Future versions could support additional hook types for comprehensive API lifecycle management.

### Other Possible Hook Types

#### 1. `timeout_hooks`

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
    timeout_hooks=[timeout_metrics_hook],
)
```

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
3. **Accept hook list in `__init__`**: `pre_hooks: Sequence[Callable[[...], None]] | None`
4. **Always include metrics hook first**, then extend with user hooks
5. **Use `invoke_with_hooks` decorator** Decorate every API method

### Hook Development Guidelines

1. **Hook signature**: `def hook(context: <Service>ApiCallContext) -> None`
2. **No return value**: Hooks perform side effects only
3. **Error handling**: If hook raises exception, API call fails
4. **Unused context**: Use `_` prefix if context not needed (`_context`)

## References

- Implementation: [SlackApi](../../../qontract_utils/qontract_utils/slack_api.py), [Factory](../../qontract_api/integrations/slack_usergroups/slack_factory.py)
- Related: [ADR-004](ADR-004-centralized-rate-limiting-via-hooks.md) - Centralized Rate Limiting (uses hook system)
- External: [Middleware pattern](https://en.wikipedia.org/wiki/Middleware), [Hook pattern](https://en.wikipedia.org/wiki/Hooking)
