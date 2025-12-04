# ADR-005: Python Asyncio Method Guidelines

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

The qontract-api service operates in multiple execution contexts (AsyncIO event loop and synchronous):

1. **FastAPI endpoints**: Run in an async event loop (uvloop) - native async support
2. **Background workers**: Run in synchronous context (Celery) - no event loop
3. **3rd party integrations**: Most external APIs are sync-only (GitLab, Jira, Slack, Vault)
4. **Python libraries**: Many libraries only provide sync interfaces

Initial attempts to support both async and sync contexts with "sync-first with async_ prefix" pattern led to complexity:

- Event loop detection patterns were fragile
- `loop.run_until_complete()` failed with uvloop
- Mixing sync/async code caused runtime errors

However, a strict "sync-only everywhere" policy is unnecessarily restrictive for code that:

- **Only runs in FastAPI async context** (e.g., API router endpoints, HTTP middleware)
- **Never calls sync-only backends** (e.g., no 3rd party API calls, no sync-only libraries)
- **Benefits from async** (e.g., `asyncio.sleep()` for polling, concurrent I/O operations)

## Decision

**Default to sync methods everywhere. Use async only in FastAPI-exclusive code with clear benefits.**

### When to Use Sync (Default)

1. **Services and business logic**: Always sync (may be reused in background workers or scripts)
2. **3rd party API integrations**: Always sync (GitLab, Jira, Slack, Vault are sync-only)
3. **Cache backends**: Always sync (used in both FastAPI and background workers)
4. **Python libraries**: Always sync (most libraries don't provide async interfaces)
5. **Shared utilities**: Always sync (could be called from anywhere)
6. **When uncertain**: Default to sync (safer choice)

### When Async is Allowed (Exception)

1. **Pure FastAPI routers**: Endpoints in `routers/` that ONLY do HTTP I/O (no sync-only calls)
2. **HTTP middleware**: Middleware that only runs in FastAPI event loop
3. **FastAPI-exclusive helpers**: Utilities like `tasks/_utils.py` polling helpers
4. **Clear async benefit**: `asyncio.sleep()` for non-blocking polling, pure async I/O

**Rule of Thumb:** If the code calls any sync-only library/API or might run outside FastAPI → use sync

### How FastAPI Handles Both

- **Async endpoints** (`async def`): Run directly in event loop, can use `await`
- **Sync endpoints** (`def`): Run in thread pool (`anyio.to_thread.run_sync`), no `await`

## Key Points

1. **Sync is the default** - use everywhere unless you have a specific reason for async
2. **Async is the exception** - only for FastAPI-exclusive code with clear benefits
3. **Never mix async/sync** in ways that require event loop detection
4. **3rd party APIs are sync-only** - GitLab, Jira, Slack, Vault have no async clients
5. **Services calling sync APIs must be sync** - cannot await sync-only library calls
6. **Pure routers can be async** - if they ONLY do HTTP I/O (no sync API calls)

## Examples

### ✅ Good: Async Helper for FastAPI-Only Polling

```python
# qontract_api/tasks/utils.py
async def wait_for_task_completion[T: TaskResult](
    get_task_status: Callable[[], T],
    timeout_seconds: int | None,
) -> T:
    """FastAPI-only helper for blocking GET endpoints."""
    if timeout_seconds is None:
        return get_task_status()

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        result = get_task_status()
        if result.status in {TaskStatus.SUCCESS, TaskStatus.FAILED}:
            return result
        await asyncio.sleep(0.5)  # Non-blocking sleep in event loop

    raise HTTPException(408, "Task still pending")
```

**Why async is OK here:**

- Only used in FastAPI endpoints (never in Celery)
- Uses `await asyncio.sleep()` for non-blocking polling
- Clear benefit over `time.sleep()` which blocks the thread

### ✅ Good: Async FastAPI Endpoint

```python
# qontract_api/integrations/slack_usergroups/router.py
@router.get("/reconcile/{task_id}")
async def get_reconcile_result(
    task_id: str,
    timeout_seconds: int | None = None,
) -> SlackUsergroupsTaskResult:
    """Async endpoint uses async helper."""
    def get_status() -> SlackUsergroupsTaskResult:
        # Sync status retrieval (calls sync cache)
        return cache.get_obj(f"task:{task_id}:result")

    # Async polling with non-blocking sleep
    return await wait_for_task_completion(get_status, timeout_seconds)
```

**Why this works:**

- Endpoint is `async def` (runs in event loop)
- Calls async helper with `await`
- Inner `get_status()` is sync (calls sync cache)
- No event loop detection needed

### ✅ Good: Sync Service with 3rd Party API

```python
# qontract_api/integrations/slack_usergroups/service.py
class SlackUsergroupsService:
    """Sync service - calls sync-only Slack API."""

    def reconcile(self, workspaces, dry_run):
        # Slack API is sync-only (no async client)
        slack_client = SlackAPI(token)
        usergroups = slack_client.usergroups_list()  # Sync call
        return self._process_usergroups(usergroups)
```

**Why sync is required:**

- Calls sync-only 3rd party API (Slack, GitLab, Jira, etc.)
- Cannot use `await` with sync-only libraries
- May be reused in background workers or scripts

### ✅ Good: Sync Cache Backend

```python
# qontract_api/cache/base.py
class CacheBackend(ABC):
    """Sync-only cache - works everywhere."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Sync method - no await."""
        ...
```

**Why sync is required:**

- Used by both FastAPI endpoints and background workers
- Cache backend (Valkey/Redis/DynamoDB/Firestore/... client) may does not have async client
- Must work in all execution contexts

### ❌ Bad: Mixing Async/Sync with Event Loop Detection

```python
# DON'T DO THIS
def get(self, key: str):
    try:
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(self.async_get(key))  # FAILS
    except RuntimeError:
        return asyncio.run(self.async_get(key))
```

**Why this fails:**

- `loop.run_until_complete()` fails with uvloop
- Context-dependent behavior is fragile
- Hard to test and debug

## Implementation Guidelines

### Decision Tree: Async or Sync?

```text
Does this code call sync-only libraries/APIs? (Slack, GitLab, Jira, Vault, most Python libs)
├─ Yes: ✅ Use sync (required - cannot await sync calls)
└─ No: Is this a service, cache, or business logic?
    ├─ Yes: ✅ Use sync (default - may be reused in workers/scripts)
    └─ No: Is this ONLY used in FastAPI? (router, middleware, helper)
        ├─ Yes: Does async provide clear benefit? (asyncio.sleep, pure async I/O)
        │   ├─ Yes: ✅ Use async
        │   └─ No: Use sync (simpler)
        └─ No (or uncertain): ✅ Use sync (default)
```

### Pattern 1: Sync Endpoint with Sync Service

```python
# Service: Sync (calls sync-only Slack API)
class SlackUsergroupsService:
    def reconcile(self, workspaces, dry_run):
        # All sync - Slack API is sync-only
        slack_client = SlackAPI(token)  # Sync client
        state = slack_client.usergroups_list()  # Cannot await
        actions = self._calculate_actions(state)
        return self._apply_actions(actions)

# Endpoint: Sync (runs in thread pool)
@router.post("/reconcile")
def create_task(...):  # Sync is fine (runs in thread pool)
    service = SlackUsergroupsService(...)
    result = service.reconcile(...)  # No await (service is sync)
    return result
```

### Pattern 2: Async Endpoint with Async Helper

```python
# Helper: Async (FastAPI-only, benefits from async)
async def wait_for_task_completion[T](
    get_status: Callable[[], T],
    timeout_seconds: int | None,
) -> T:
    while not_complete:
        await asyncio.sleep(0.5)  # Non-blocking
    return result

# Endpoint: Async (uses async helper)
@router.get("/reconcile/{task_id}")
async def get_result(task_id: str, timeout: int | None):
    return await wait_for_task_completion(
        get_status=lambda: fetch_from_cache(task_id),
        timeout_seconds=timeout,
    )
```

### Pattern 3: Sync Cache and 3rd Party Integrations

```python
# Cache: Always sync (Valkey client is sync-only)
class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Sync - Valkey has no async client."""
        ...

class RedisCacheBackend(CacheBackend):
    def __init__(self, redis: Valkey):  # Sync-only client
        self.client = redis

    def get(self, key: str) -> Any | None:
        value = self.client.get(key)  # Cannot await
        return json.loads(value) if value else None

# GitLab: Always sync (GitLab API is sync-only)
class GitLabService:
    def fetch_projects(self):
        gitlab_client = GitLabAPI(token)  # Sync client
        projects = gitlab_client.projects.list()  # Cannot await
        return self._process_projects(projects)
```

## Consequences

### Positive

- **Flexibility**: Can use async where it provides clear benefits (polling, pure HTTP I/O)
- **Performance**: Async helpers like `wait_for_task_completion` don't block threads
- **Simplicity**: Sync services/caches remain simple and work everywhere
- **Clarity**: Clear distinction between FastAPI-only (can be async) and shared (must be sync)
- **Compatibility**: Works with sync-only 3rd party APIs (GitLab, Jira, Slack, Vault)

### Negative

- **Cognitive Load**: Developers must understand when async is appropriate
- **Testing**: Async tests require `@pytest.mark.asyncio` and proper fixtures
- **Limited async ecosystem**: Cannot use async with most 3rd party integrations

**Mitigation:**

- Decision tree in this ADR provides clear guidance
- Default to sync when uncertain (safe choice)
- Most code is sync anyway (due to sync-only 3rd party APIs)
- Code reviews enforce the pattern
- Examples in integration tests demonstrate proper usage

## Alternatives Considered

### 1. Strict Sync-Only (Original ADR-005)

**Pros:**

- Simplest approach
- No async complexity
- Works identically everywhere

**Cons:**

- `time.sleep()` blocks threads in polling scenarios
- Cannot leverage async benefits where appropriate
- **Rejected:** Too restrictive for FastAPI-only utilities

### 2. Pure Async Everywhere

**Pros:**

- Best async performance
- Native async ecosystem integration

**Cons:**

- Doesn't work with background workers (sync-only)
- Requires async versions of all 3rd party APIs (GitLab, Jira, Slack - don't exist)
- Most Python libraries are sync-only
- **Rejected:** Incompatible with sync-only ecosystem

### 3. Event Loop Detection Pattern

**Pros:**

- Automatically adapts to context
- Single codebase for both contexts

**Cons:**

- Fragile, context-dependent behavior
- `loop.run_until_complete()` fails with uvloop
- Hard to debug and test
- **Rejected:** Too error-prone in practice

## References

- FastAPI Async: <https://fastapi.tiangolo.com/async/>
- Python Async/Await: <https://docs.python.org/3/library/asyncio.html>
- Implementation: `qontract_api/tasks/_utils.py` (async helper)
- Implementation: `qontract_api/cache/base.py` (sync cache)

## Lessons Learned

### The Event Loop Detection Attempt

Initially, we tried to support both async (FastAPI) and sync (Celery) contexts with "smart wrappers":

```python
def get(self, key):
    try:
        loop = asyncio.get_running_loop()  # Detect FastAPI context
        return loop.run_until_complete(self.async_get(key))  # FAILS with uvloop!
    except RuntimeError:
        return asyncio.run(self.async_get(key))  # Celery context
```

**Problem:** `loop.run_until_complete()` raises `RuntimeError: this event loop is already running` in uvloop.

**Why It Failed:**

- Standard asyncio allows nested `run_until_complete()` calls (fragile)
- uvloop enforces strict event loop rules (correct behavior)
- No reliable way to run async code synchronously in a running event loop

**Solution:** Use async only where it's FastAPI-specific and provides clear benefits. Keep shared code sync.

### Takeaways

1. **Async/Sync Mixing is Dangerous**: Runtime errors, context-dependent behavior, hard to debug
2. **Use Async Selectively**: Only in FastAPI-only code with clear benefits
3. **Shared Code Must Be Sync**: Cache, services, core logic
4. **Trust the Framework**: FastAPI handles both async and sync endpoints well
