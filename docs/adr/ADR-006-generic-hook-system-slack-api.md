# ADR-006: Generic Hook System for API Wrappers

**Status:** Accepted
**Date:** 2026-02-06
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

API wrappers (Slack, GitHub, GitLab, AWS, etc.) and standalone utility functions need to support multiple cross-cutting concerns:

- **Prometheus metrics**: Track all API calls with method/verb/service labels
- **Rate limiting**: Enforce rate limits before API calls
- **Logging**: Debug/trace API calls with context
- **Tracing**: Distributed tracing with OpenTelemetry (future)
- **Authentication**: Token refresh, credential rotation (future)
- **Retry logic**: Automatic retries with exponential backoff

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

**3. Hooks Dataclass** (aggregates all hook parameters):

```python
from qontract_utils.hooks import Hooks

class Hooks(BaseModel, frozen=True):
    """Hook configuration for API clients."""

    pre_hooks: list[Callable[..., None]] = Field(default_factory=list)
    post_hooks: list[Callable[..., None]] = Field(default_factory=list)
    error_hooks: list[Callable[..., None]] = Field(default_factory=list)
    retry_hooks: list[Callable[..., None]] = Field(default_factory=list)
    retry_config: RetryConfig | None = None # No retries by default
```

**Why Hooks Dataclass:**

- Simplifies constructor signatures (1 parameter instead of 5)
- Groups related configuration together
- Makes hook management cleaner and more maintainable

**4. Built-in Hooks** (always included):

```python
def _metrics_hook(context: SlackApiCallContext) -> None:
    """Built-in hook for Prometheus metrics."""
    slack_request.labels(context.method, context.verb).inc()
```

**5. Class Decorator (`@with_hooks`)** for automatic hook initialization:

```python
from qontract_utils.hooks import Hooks, with_hooks

@with_hooks(hooks=Hooks(
    pre_hooks=[_metrics_hook, _latency_start_hook],
    post_hooks=[_latency_end_hook],
))
class SlackApi:
    def __init__(self, ..., hooks: Hooks | None = None):
        # self._hooks automatically set by decorator (built-in + user hooks merged)
        pass
```

The `@with_hooks` decorator:

- Intercepts the `hooks` parameter from `__init__`
- Merges built-in hooks (from decorator) with user hooks (from parameter)
- Sets `self._hooks` automatically before `__init__` runs
- Built-in hooks are prepended BEFORE user hooks

**6. Method Decorator (`@invoke_with_hooks`)** for hook execution:

Instance methods (retrieves hooks from `self._hooks`):

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

Standalone functions and static methods (hooks passed directly in decorator):

```python
@invoke_with_hooks(
    context_factory=lambda: MyContext(method="process", verb="POST"),
    hooks=Hooks(
        pre_hooks=[logging_hook],
        retry_config=RetryConfig(on=Exception, attempts=3),
    )
)
def process_data(data: dict) -> dict:
    # Process data with automatic hooks and retry support
    return transform(data)
```

Class static methods:

```python
class DataProcessor:
    @staticmethod
    @invoke_with_hooks(
        context_factory=lambda: ProcessContext(operation="validate"),
        hooks=Hooks(pre_hooks=[metrics_hook], retry_config=NO_RETRY_CONFIG)
    )
    def validate(data: dict) -> bool:
        return schema.validate(data)
```

## Usage Patterns

The hook system supports three distinct usage patterns depending on your needs:

### Pattern 1: Instance Methods (Recommended for API Clients)

Use `@with_hooks` class decorator to define built-in hooks and `@invoke_with_hooks(context_factory)` method decorator on instance methods. The class decorator automatically merges built-in hooks with user-provided hooks and sets `self._hooks`. The method decorator retrieves hooks from `self._hooks`.

```python
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

@with_hooks(hooks=Hooks(
    pre_hooks=[_metrics_hook, _latency_start_hook],
    post_hooks=[_latency_end_hook],
))
class SlackApi:
    def __init__(self, workspace_name: str, token: str, hooks: Hooks | None = None):
        # self._hooks automatically set by @with_hooks decorator (built-in + user hooks merged)
        self.workspace_name = workspace_name
        self._sc = SlackClient(token=token)

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="chat.postMessage",
            verb="POST",
            workspace=self.workspace_name
        )
    )
    def chat_post_message(self, text: str) -> None:
        self._sc.chat_postMessage(channel=self.channel, text=text)
```

**When to use:** API wrapper classes, service clients

### Pattern 2: Standalone Functions

Use `@invoke_with_hooks(context_factory, hooks=...)` decorator on standalone functions. Hooks are passed directly in the decorator.

```python
from qontract_utils.hooks import Hooks, invoke_with_hooks

@invoke_with_hooks(
    context_factory=lambda: {"operation": "transform"},
    hooks=Hooks(
        pre_hooks=[logging_hook],
        retry_config=RetryConfig(on=TransformError, attempts=3),
    )
)
def transform_data(data: dict) -> dict:
    return process(data)

# Direct call - hooks execute automatically
result = transform_data({"key": "value"})
```

**When to use:** Utility functions, data transformers, standalone operations

### Pattern 3: Class Static Methods

Use `@staticmethod` combined with `@invoke_with_hooks(context_factory, hooks=...)` decorator.

```python
class DataValidator:
    @staticmethod
    @invoke_with_hooks(
        context_factory=lambda: {"operation": "validate"},
        hooks=Hooks(
            pre_hooks=[metrics_hook],
            retry_config=NO_RETRY_CONFIG,
        )
    )
    def validate_schema(data: dict) -> bool:
        return schema.validate(data)

# Call via class or instance
DataValidator.validate_schema(data)
```

**When to use:** Stateless operations in classes, validators, pure functions grouped in classes

### Pattern 4: Direct Invocation (Hooks.invoke)

Use `hooks.invoke()` or `hooks.with_context().invoke()` for one-off function calls without decorators.

```python
def fetch_data(url: str) -> dict:
    return requests.get(url).json()

hooks = Hooks(
    pre_hooks=[rate_limit_hook],
    retry_config=RetryConfig(on=RequestError, attempts=3),
)

# Without context
result = hooks.invoke(fetch_data, "https://api.example.com/data")

# With context
context = {"endpoint": "/data", "method": "GET"}
result = hooks.with_context(context).invoke(fetch_data, "https://api.example.com/data")
```

**When to use:** One-off operations, testing, wrapping third-party functions

## Implementation Example: SlackApi

### Complete Implementation

```python
from dataclasses import dataclass
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

@dataclass(frozen=True)
class SlackApiCallContext:
    """Context for Slack API calls."""
    method: str
    verb: str
    workspace: str

def _metrics_hook(context: SlackApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    slack_request.labels(context.method, context.verb).inc()

def _latency_start_hook(context: SlackApiCallContext) -> None:
    """Built-in latency tracking hook."""
    _latency_tracker.set(time.perf_counter())

def _latency_end_hook(context: SlackApiCallContext) -> None:
    """Built-in latency tracking hook."""
    duration = time.perf_counter() - _latency_tracker.get()
    slack_request_duration.labels(context.method, context.verb).observe(duration)

@with_hooks(hooks=Hooks(
    pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
    post_hooks=[_latency_end_hook],
))
class SlackApi:
    def __init__(
        self,
        workspace_name: str,
        token: str,
        hooks: Hooks | None = None,  # User-provided hooks (merged by @with_hooks)
    ) -> None:
        # self._hooks automatically set by @with_hooks decorator
        # Built-in hooks (metrics, logging, latency) + user hooks are merged
        self.workspace_name = workspace_name
        self._sc = SlackClient(token=token)

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
from qontract_utils.hooks import Hooks

def create_slack_api(workspace_name: str, token: str, cache: CacheBackend, settings: Settings) -> SlackApi:
    token_bucket = TokenBucket(cache=cache, bucket_name=f"slack:{workspace_name}", ...)

    def rate_limit_hook(_context: SlackApiCallContext) -> None:
        token_bucket.acquire(tokens=1, timeout=30)

    # Built-in hooks (metrics, logging, latency) automatically included via @with_hooks
    # User hooks (rate_limit_hook) are appended after built-in hooks
    return SlackApi(
        workspace_name,
        token,
        hooks=Hooks(pre_hooks=[rate_limit_hook]),
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

    # Built-in hooks (metrics, logging, latency) automatically included via @with_hooks
    # User hooks are appended after built-in hooks
    return SlackApi(
        workspace_name,
        token,
        hooks=Hooks(
            pre_hooks=[
                rate_limit_hook,    # Executed after built-in pre_hooks
                logging_hook,       # Executed next
                tracing_hook,       # Executed next
            ],
            post_hooks=[post_api_call_hook], # Executed after built-in post_hooks
            error_hooks=[error_handling_hook], # Executed on API call errors
        ),
    )
```

**Hook Execution Order (with `@with_hooks` merging):**

1. **Built-in `_metrics_hook`** (from `@with_hooks`) - Prometheus metrics
2. **Built-in `_request_log_hook`** (from `@with_hooks`) - Request logging
3. **Built-in `_latency_start_hook`** (from `@with_hooks`) - Latency tracking
4. **User `rate_limit_hook`** (from `hooks=Hooks(...)`) - Blocks if rate limit exceeded
5. **User `logging_hook`** (from `hooks=Hooks(...)`) - Logs API call details
6. **User `tracing_hook`** (from `hooks=Hooks(...)`) - Creates tracing span (future)
7. **Actual API call** - `slack_client.chat_postMessage(...)`
8. **Built-in `_latency_end_hook`** (from `@with_hooks`) - Record latency
9. **User `post_api_call_hook`** (from `hooks=Hooks(...)`) - Post-call processing

**Key Points:**

- Built-in hooks (from `@with_hooks` decorator) are prepended BEFORE user hooks
- User hooks (from `hooks=Hooks(...)` parameter) are appended after built-in hooks
- Hooks execute sequentially in order
- If any hook raises exception, API call is aborted
- Hook merging is automatic and transparent to the caller

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
    hooks=Hooks(
        retry_config=RetryConfig(on=SlackApiError, attempts=5),
        retry_hooks=[breaker.retry_hook],
    ),
)
```

### Hook Execution Order with Retry

**Overall flow:**

```text
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
   - Built-in hooks first (from `@with_hooks`): metrics, logging, latency start
   - User hooks next (from `hooks=Hooks(...)`): rate limiting, custom logging, etc.

2. **Retry Context** (stamina)
   - Attempt 1: Direct API call
   - Attempt 2..N: **Retry hooks** (with attempt number) → API call

3. **Error hooks** (only on final failure, after retry_context)
   - Called ONLY when all retries are exhausted
   - In except-block after retry_context
   - Only user-provided error hooks (not merged with built-in)

4. **Post-hooks** (always, after retry_context)
   - In finally-block (runs on success AND failure)
   - Built-in hooks first (from `@with_hooks`): latency recording
   - User hooks next (from `hooks=Hooks(...)`): cleanup operations

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
from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, Hooks, RetryConfig
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
    hooks=Hooks(retry_config=retry_config),
)

# Example 2: Without retry (explicit)
api_no_retry = SlackApi(
    workspace_name="app-sre",
    token=token,
    hooks=Hooks(retry_config=None),  # Explicit: no retries
)

# Example 3: Default behavior (stamina defaults: attempts=10, timeout=45s)
api_default = SlackApi(
    workspace_name="app-sre",
    token=token,
    hooks=Hooks(retry_config=DEFAULT_RETRY_CONFIG),  # Uses stamina defaults
)
```

## Context-Aware Factories

Context factories can now receive the decorated method's arguments by declaring matching parameter names in the factory signature. This enables hooks to access method-specific data (e.g., path, mount_point) for rich, structured logging and metrics.

### Pattern Evolution

**Before (static context — factory only receives self):**

```python
@invoke_with_hooks(
    lambda self: VaultApiCallContext(
        method="secrets.kv.v2.read_secret_version",
        id=self._settings.server,
    )
)
def _read_kv_v2_secret(self, path: str, mount_point: str, version: int | None) -> dict:
    ...
```

Context is static — hooks cannot access `path` or `mount_point` values passed to the method at runtime.

**After (context-aware — factory receives method args):**

```python
@invoke_with_hooks(
    lambda self, path, mount_point: VaultApiCallContext(
        method="secrets.kv.v2.read_secret_version",
        id=self._settings.server,
        path=path,
        mount_point=mount_point,
    )
)
def _read_kv_v2_secret(self, path: str, mount_point: str, version: int | None) -> dict:
    ...
```

Context is dynamic — the factory receives actual `path` and `mount_point` values at call time, enabling hooks to produce meaningful output like `"Slow Vault request: path=secret/app1/token, mount_point=app-sre, duration=2.3s"`.

### Argument Forwarding Rules

1. **Parameter name matching**: Factory parameters must match method parameter names exactly (case-sensitive)
2. **Self parameter**: `self` in factory is matched by name against the method's `self` parameter — it receives the class instance. Factories that don't need the instance can omit `self`.
3. **Subset selection**: Factory can declare a subset of the method's parameters — only declare what you need
4. **Validation at decoration time**: Mismatched parameter names raise `TypeError` when `@invoke_with_hooks` is applied (fail-fast)
5. **Cached signature inspection**: Signature inspection is performed once per factory and cached using a composite key `(id, code_hash)` — no per-call overhead
6. **Backward compatible**: Existing factories with no args (`lambda: ...`) or self-only (`lambda self: ...`) continue to work unchanged — this is an opt-in feature

### Use Cases

**Slow request logging** (Vault example):

```python
def _slow_request_hook(context: VaultApiCallContext) -> None:
    """Log slow Vault requests with path and mount_point."""
    stack = _latency_tracker.get()
    if not stack:
        return
    duration = time.perf_counter() - stack[-1]
    if duration <= 1.0:
        return
    # Context has path and mount_point from method args
    logger.warning(
        "Slow Vault request",
        path=context.path,
        mount_point=context.mount_point,
        duration=f"{duration:.1f}s",
    )
```

**Metrics with labels** (method-specific dimensions):

```python
def _metrics_hook(context: SlackApiCallContext) -> None:
    """Track API calls with method and workspace labels."""
    slack_request.labels(
        method=context.method,
        workspace=context.workspace,  # From factory arg forwarding
    ).inc()
```

**Rate limiting per resource**:

```python
@invoke_with_hooks(
    lambda self, repo_owner, repo_name: GitHubApiCallContext(
        method="repos.get",
        owner=repo_owner,
        repo=repo_name,
    )
)
def get_repo(self, repo_owner: str, repo_name: str) -> dict:
    ...

def rate_limit_hook(context: GitHubApiCallContext) -> None:
    """Apply rate limits per repository."""
    bucket_key = f"github:{context.owner}/{context.repo}"
    token_bucket.acquire(bucket_key, tokens=1)
```

### Migration Guidance

**No migration required** — existing context factories continue to work unchanged. Adopt arg forwarding incrementally when hooks need method-specific data:

1. Add optional fields to your context dataclass (e.g., `path: str | None = None`)
2. Update factory signature to declare method args (e.g., `lambda self, path: ...`)
3. Pass arg values to context constructor (e.g., `path=path`)
4. Update hooks to use new context fields

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
    hooks=Hooks(timeout_hooks=[timeout_metrics_hook]),
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
2. **Create built-in hooks** (metrics, logging, latency tracking)
3. **Apply `@with_hooks` class decorator** with built-in hooks
4. **Accept `hooks: Hooks | None = None` in `__init__`** for user-provided hooks
5. **Decorate every API method** with `@invoke_with_hooks(context_factory)`

**Class Pattern:**

```python
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

@with_hooks(hooks=Hooks(
    pre_hooks=[_metrics_hook, _latency_start_hook],
    post_hooks=[_latency_end_hook],
))
class MyApi:
    def __init__(self, ..., hooks: Hooks | None = None) -> None:
        # self._hooks automatically set by @with_hooks decorator
        # Built-in hooks merged with user hooks (built-in first)
        ...

    @invoke_with_hooks(lambda self: MyApiCallContext(method="do_thing", verb="POST"))
    def do_thing(self) -> None:
        self._client.do_thing()
```

### Hook Development Guidelines

1. **Hook signature**: `def hook(context: <Service>ApiCallContext) -> None`
2. **No return value**: Hooks perform side effects only
3. **Error handling**: If hook raises exception, API call fails
4. **Unused context**: Use `_` prefix if context not needed (`_context`)

## References

- Implementation: [SlackApi](../../../qontract_utils/qontract_utils/slack_api.py), [Factory](../../qontract_api/integrations/slack_usergroups/slack_factory.py)
- Related: [ADR-004](ADR-004-centralized-rate-limiting-via-hooks.md) - Centralized Rate Limiting (uses hook system)
- External: [Middleware pattern](https://en.wikipedia.org/wiki/Middleware), [Hook pattern](https://en.wikipedia.org/wiki/Hooking)
