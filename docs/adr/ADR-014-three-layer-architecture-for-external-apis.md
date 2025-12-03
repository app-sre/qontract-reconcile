# ADR-014: Three-Layer Architecture for External API Integrations

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

When integrating with external APIs (REST, GraphQL, etc.) in multi-process environments like FastAPI + Celery, we face several challenges:

**Current Situation:**

- Monolithic API client classes mix API communication, caching, and business logic
- Each process has its own in-memory cache with no sharing across workers
- No TTL support leads to stale cached data
- No distributed locking causes race conditions during concurrent cache updates
- Tight coupling makes testing and mocking difficult

**Problems:**

- **No shared cache:** API workers and background workers can't share cached data
- **Stale data:** Cached data never expires automatically
- **Race conditions:** Multiple processes updating cache simultaneously causes corruption
- **Mixed concerns:** API client handles communication, caching, and business logic
- **Poor testability:** Hard to mock individual components

**Requirements:**

- Shared cache across multiple processes (FastAPI workers + Celery workers)
- Distributed locking for thread-safe cache updates
- TTL support to automatically expire stale data
- Clear separation between API communication, caching, and business logic
- Type safety with Pydantic models
- Easy to test and mock at each layer

**Constraints:**

- Must work in multi-process environment (no shared memory)
- Must minimize external API calls (rate limits, latency)
- Must be thread-safe across distributed processes
- Backward compatible migration path for existing code

## Decision

We adopt a **three-layer architecture** that separates concerns for external API integrations:

**Layer 1: API Client (Pure Communication)**

- Stateless wrapper around external API
- Handles HTTP/gRPC/GraphQL calls, retries, errors
- Returns typed Pydantic models
- No caching, no state, no business logic

**Layer 2: Workspace Client (Cache + Compute)**

- Manages distributed cache with TTL
- Implements distributed locking for thread-safety
- Provides compute helpers (filtering, lookups)
- Uses Layer 1 for API communication

**Layer 3: Service (Business Logic)**

- Implements use cases and orchestration
- Uses Layer 2 for data access
- Handles dry-run mode, state transitions
- Pure business logic, no direct API calls

### Key Points

- **Separation of concerns:** Each layer has one responsibility
- **Shared cache:** Redis/DynamoDB cache shared across all processes
- **Distributed locking:** Thread-safe updates using cache backend locks
- **Type safety:** Pydantic models throughout all layers
- **Testability:** Mock boundaries at each layer

## Alternatives Considered

### Alternative 1: Monolithic API Client (Current State)

Single class handles API communication, caching, and business logic.

```python
class ExternalApiClient:
    def __init__(self):
        self._cache = {}  # In-memory cache per instance

    def get_resources(self):
        if self._cache.get("resources"):
            return self._cache["resources"]

        resources = self._api_call("/resources")
        self._cache["resources"] = resources  # No TTL, no locking
        return resources

    def reconcile(self, desired_state):
        # Business logic mixed with caching
        ...
```

**Pros:**

- Simple single-class implementation
- Easy to understand for small projects
- No additional dependencies

**Cons:**

- No shared cache across processes (each instance has own cache)
- No TTL support (stale data never expires)
- No distributed locking (race conditions)
- Mixed concerns (hard to test, tight coupling)
- Can't reuse API client in different contexts

### Alternative 2: Two-Layer Architecture

Combine caching and business logic in one layer, separate from API client.

```python
# Layer 1: API Client
class ApiClient:
    def list_resources(self): ...

# Layer 2: Service (cache + business logic)
class Service:
    def __init__(self, api_client, cache):
        self.api_client = api_client
        self.cache = cache

    def get_resources(self):
        # Caching logic
        ...

    def reconcile(self, desired_state):
        # Business logic
        ...
```

**Pros:**

- Separates API communication from application logic
- Shared cache possible
- Simpler than three layers (fewer classes)

**Cons:**

- Cache logic and business logic still mixed
- Hard to reuse caching patterns across services
- Compute helpers (filtering, lookups) mixed with business logic
- Testing requires mocking both cache and business logic together

### Alternative 3: Three-Layer Architecture (Selected)

Separate API communication, caching+compute, and business logic into distinct layers.

**Pros:**

- Clear separation of concerns (one responsibility per layer)
- Shared cache with distributed locking
- TTL support for automatic stale data expiration
- Reusable cache patterns (DRY helpers with TypeVar)
- Easy to test (mock at each layer boundary)
- Layer 1 reusable across projects
- Type-safe with Pydantic throughout

**Cons:**

- More classes/files than simpler approaches
- Migration effort for existing code
- Developers must understand three-layer pattern
  - **Mitigation:** Clear documentation, examples, and code templates provided

## Consequences

### Positive

- **Clear separation of concerns:** Each layer has single, well-defined responsibility
- **Shared cache:** All processes share same Redis/DynamoDB cache
- **Thread-safe:** Distributed locking prevents race conditions
- **Performance:** Cache updates (O(1)) instead of invalidation (O(n))
- **Type-safe:** Pydantic models ensure correctness
- **Testable:** Mock boundaries at each layer independently
- **Reusable:** Layer 1 API clients can be shared across projects
- **TTL support:** Automatic stale data expiration

### Negative

- **More complex:** Three layers instead of one class
  - **Mitigation:** Provide templates and examples (e.g., SlackApi refactoring)
  - **Mitigation:** Document patterns in ADRs and implementation guides

- **Migration effort:** Existing code needs refactoring
  - **Mitigation:** Keep old methods for backward compatibility during migration
  - **Mitigation:** Gradual migration path (add new methods alongside old)

- **Lock contention:** Possible under heavy concurrent writes
  - **Mitigation:** Use double-check locking pattern to minimize lock duration
  - **Mitigation:** Lock only during cache writes, not reads

- **Learning curve:** Developers must understand layer responsibilities
  - **Mitigation:** Clear documentation with examples
  - **Mitigation:** Code reviews to ensure proper layer usage

## Implementation Guidelines

### Layer 1: API Client (Pure Communication)

Lives in shared utilities package (e.g., `qontract_utils/external_api/`).

```python
class ExternalApiClient:
    """Pure API client - stateless, no caching."""

    def list_resources(self) -> list[Resource]:
        """Fetch all resources from API."""
        response = self._http_client.get("/resources")
        return [Resource(**item) for item in response.json()]

    def update_resource(self, resource_id: str, **kwargs) -> Resource:
        """Update a resource via API."""
        response = self._http_client.patch(f"/resources/{resource_id}", json=kwargs)
        return Resource(**response.json())
```

**Checklist:**

- [ ] Stateless (no instance variables for caching)
- [ ] Returns typed Pydantic models
- [ ] Handles retries, timeouts, error codes
- [ ] No business logic
- [ ] Easy to mock (HTTP client dependency)

### Layer 2: Workspace Client (Cache + Compute)

Lives in application code (e.g., `qontract_api/integrations/external_api/`).

```python
T = TypeVar("T", bound=BaseModel)

class WorkspaceClient:
    """Cache + compute layer with distributed locking."""

    def __init__(
        self,
        api_client: ExternalApiClient,
        cache: CacheBackend,
        settings: Settings,
    ):
        self.api_client = api_client
        self.cache = cache
        self.settings = settings

    def get_resources(self) -> dict[str, Resource]:
        """Get all resources (cached with distributed locking)."""
        cache_key = self._cache_key_resources()

        # Try cache first (no lock for reads)
        if cached := self._get_cached_dict(cache_key, Resource):
            return cached

        # Fetch with distributed lock
        with self.cache.lock(cache_key):
            # Double-check after acquiring lock
            if cached := self._get_cached_dict(cache_key, Resource):
                return cached

            # Fetch from API
            resources = {r.id: r for r in self.api_client.list_resources()}

            # Cache with TTL
            self._set_cached_dict(cache_key, resources, self.settings.cache_ttl)
            return resources

    def get_resource_by_name(self, name: str) -> Resource | None:
        """Compute helper - find resource by name."""
        resources = self.get_resources()
        for resource in resources.values():
            if resource.name == name:
                return resource
        return None

    def _get_cached_dict(self, cache_key: str, cls: type[T]) -> dict[str, T] | None:
        """Get cached dict with automatic deserialization."""
        if cached_str := self.cache.get(cache_key):
            cached_list = json_loads(cached_str)
            return {obj["id"]: cls(**obj) for obj in cached_list}
        return None

    def _set_cached_dict(self, cache_key: str, obj_dict: dict[str, T], ttl: int) -> None:
        """Set cached dict with automatic serialization."""
        obj_list = [obj.model_dump() for obj in obj_dict.values()]
        self.cache.set(cache_key, json_dumps(obj_list), ttl)
```

**Checklist:**

- [ ] Uses Layer 1 for API communication
- [ ] Implements distributed locking for cache updates
- [ ] Uses double-check locking pattern
- [ ] Provides DRY cache helpers with TypeVar
- [ ] Cache updates instead of invalidation (ADR-015)
- [ ] Includes compute helpers (filtering, lookups)

### Layer 3: Service (Business Logic)

Lives in application code (e.g., `qontract_api/integrations/external_api/`).

```python
class ReconciliationService:
    """Business logic for reconciliation."""

    def __init__(self, workspace_client: WorkspaceClient):
        self.workspace_client = workspace_client

    def reconcile(
        self,
        desired_state: list[ResourceConfig],
        *,
        dry_run: bool = True,
    ) -> ReconcileResult:
        """Reconcile desired state vs current state."""
        # Get current state from cache
        current = self.workspace_client.get_resources()

        # Compute diff
        actions = self._compute_diff(desired_state, current)

        # Execute actions (if not dry_run)
        if not dry_run:
            for action in actions:
                self._execute_action(action)

        return ReconcileResult(actions=actions)
```

**Checklist:**

- [ ] Uses Layer 2 for data access
- [ ] No direct API calls or cache management
- [ ] Pure business logic
- [ ] Handles dry-run mode
- [ ] Framework-agnostic

### Distributed Locking Pattern

Use double-check locking to minimize lock contention:

```python
def get_cached_data(self):
    cache_key = "..."

    # 1. Try cache first (no lock)
    if cached := self.cache.get(cache_key):
        return cached

    # 2. Acquire lock for fetch
    with self.cache.lock(cache_key):
        # 3. Double-check after lock
        if cached := self.cache.get(cache_key):
            return cached

        # 4. Fetch from API
        data = self.api_client.fetch_data()

        # 5. Cache with TTL
        self.cache.set(cache_key, data, ttl)
        return data
```

### When to Use This Pattern

**Use when:**

- Integrating with external APIs in multi-process environment
- Need shared cache across workers
- High read-to-write ratio (caching beneficial)
- Multiple processes/threads accessing same resources

**Don't use when:**

- Single-process application
- Low read-to-write ratio (cache overhead not worth it)
- Resources change too frequently (cache invalidation overhead)
- Simple CRUD operations without complex business logic

## References

- Related ADRs:
  - [ADR-005 (Sync-Only Development)](./ADR-005-sync-only-no-async.md)
  - [ADR-007 (No Changes to reconcile/ - Migrate Utilities to qontract_utils)](./ADR-007-no-reconcile-changes-migrate-utils.md)
  - [ADR-015 (Cache Update Strategy)](./ADR-015-cache-update-strategy.md)
- Example Implementation: SlackApi Integration
- Cache Backend: `qontract_api/qontract_api/cache/base.py`
- Distributed Locking: `CacheBackend.lock()` context manager in `qontract_api/qontract_api/cache/base.py:129-174`

---

## Notes

**Example: Slack API Integration**

This pattern was first implemented for the Slack API integration:

- **Layer 1:** `SlackApi` in `qontract_utils/slack_api/client.py`
  - Methods: `users_list()`, `usergroups_update()`, `conversations_list()`
  - Returns: `list[SlackUser]`, `SlackUsergroup`, `list[SlackChannel]`

- **Layer 2:** `SlackWorkspaceClient` in `qontract_api/integrations/slack_usergroups/slack_workspace_client.py`
  - Methods: `get_users()`, `get_usergroup_by_handle()`, `update_usergroup()`
  - Cache: Users, usergroups, channels with TTL
  - Compute: `get_users_by_ids()`, `get_channels_by_ids()`

- **Layer 3:** `SlackUsergroupsService` in `qontract_api/integrations/slack_usergroups/service.py`
  - Methods: `reconcile()`, `_compute_diff()`, `_execute_actions()`
  - Business logic: Reconcile desired vs current state

This implementation serves as a reference for other external API integrations.
