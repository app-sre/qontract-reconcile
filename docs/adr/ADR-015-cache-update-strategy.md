# ADR-015: Cache Update Instead of Invalidation

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

When modifying resources via an external API (create, update, delete), we need to keep our cache consistent. This is critical in multi-process environments where multiple workers share the same distributed cache.

**Current Situation:**

- External API integrations use distributed cache (Redis/DynamoDB) to minimize API calls
- Cache stores collections of resources (users, channels, repositories, etc.)
- Resources are modified via API calls (update usergroup, create repository, etc.)
- Cache must reflect modifications to prevent serving stale data

**Problems:**

- **Cache invalidation (traditional approach):** After updating a resource, delete the entire cached collection, forcing next read to refetch ALL resources from API
- **Wasteful API calls:** Refetching 100+ resources when only 1 changed
- **Higher latency:** Next read takes 100-500ms (API call) instead of 1-5ms (cache hit)
- **Rate limit pressure:** Uses several API calls per update (update + refetch) instead of 1

**Requirements:**

- Cache must remain consistent after resource modifications
- Minimize API calls to external services
- Respect rate limits (e.g., Slack: 20 requests/min per tier)
- Low latency for reads after updates
- Thread-safe across distributed processes

**Constraints:**

- Must work with distributed cache (no shared memory)
- Must use distributed locking for thread safety
- Resources identified by unique ID
- TTL-based cache expiration

## Decision

We adopt **cache update strategy** instead of **cache invalidation** for resource modifications.

After modifying a resource via API (create, update, delete), we **update the single resource** in the cached collection instead of deleting the entire cache.

### Key Points

- **O(1) cache update:** Modify single dict entry instead of O(n) full refetch
- **Distributed locking:** Use `cache.lock()` for thread-safe updates
- **API call reduction:** Eliminate refetch after modification
- **Immediate consistency:** Cache updated instantly, no stale data window
- **Graceful degradation:** Lock failures fall back to eventual consistency via TTL

## Alternatives Considered

### Alternative 1: Cache Invalidation (Traditional)

After modifying a resource, delete the entire cached collection:

```python
def update_resource(self, resource_id: str, **kwargs):
    # 1. Update via API
    updated = self.api_client.update_resource(resource_id, **kwargs)

    # 2. Invalidate entire cache
    self.cache.delete(cache_key)

    # Next read will refetch ALL resources
    return updated
```

**Pros:**

- Simple implementation (just delete cache key)
- No distributed locking needed
- No risk of partial cache corruption
- Works for all modification types

**Cons:**

- O(n) API refetch on next read (fetch all N resources)
- 100-500ms latency on next read (API call vs 1-5ms cache hit)
- Uses 2 API call slots (update + refetch) = 50% more rate limit usage
- Higher costs if API is metered
- Temporary stale data window between invalidation and refetch

### Alternative 2: No Caching

Don't cache at all, always fetch from API:

```python
def get_resources(self):
    # Always fetch from API, no caching
    return self.api_client.list_resources()
```

**Pros:**

- Simplest implementation
- Always fresh data
- No cache consistency issues
- No distributed locking needed

**Cons:**

- High API call volume (every read hits API)
- High latency (100-500ms per read)
- Quickly exhausts rate limits
- Higher costs if API is metered
- Not viable for high-traffic services

### Alternative 3: Cache Update (Selected)

After modifying a resource, update only that resource in the cached collection:

```python
def update_resource(self, resource_id: str, **kwargs):
    # 1. Update via API
    updated = self.api_client.update_resource(resource_id, **kwargs)

    # 2. Update single resource in cache
    with self.cache.lock(cache_key):
        cached = self._get_cached_dict(cache_key, Resource)
        if cached:
            cached[resource_id] = updated  # O(1) dict update
            self._set_cached_dict(cache_key, cached, ttl)

    return updated
```

**Pros:**

- O(1) cache update (single dict entry)
- Reduction of API calls (no refetch needed)
- 20-100x faster reads after update (cache hit vs API call)
- More rate limit capacity for other operations
- Immediate cache consistency (no stale data)
- Lower costs if API is metered

**Cons:**

- More complex than simple invalidation
- Requires distributed locking (~1-2ms overhead)
- Lock failures require fallback to eventual consistency
- TTL extends for entire collection on each update
  - **Mitigation:** Acceptable side effect, provides LRU-like behavior

## Consequences

### Positive

- **API call reduction:** Eliminate refetch after modification (several calls → 1 call)
- **20-100x latency improvement:** Next read is 1-5ms (cache) vs 100-500ms (API)
- **More rate limit capacity:** Free up API call slots for other operations
- **Immediate consistency:** Cache updated instantly, no stale data window
- **Lower costs:** Fewer API calls if external service charges per request
- **Better UX:** Faster response times for users

### Negative

- **More complex:** Requires distributed locking and update logic
  - **Mitigation:** Provide generic `_update_cached_dict()` helper with TypeVar
  - **Mitigation:** Document pattern in ADR and implementation guide

- **Lock overhead:** Adds ~1-2ms per update
  - **Mitigation:** Negligible compared to API latency (100-500ms)
  - **Mitigation:** Only lock during writes, not reads

- **Lock contention:** Possible under heavy concurrent writes
  - **Mitigation:** Use double-check locking pattern for reads
  - **Mitigation:** Lock failures gracefully degrade to eventual consistency

- **TTL extension:** Updates extend TTL for entire collection
  - **Mitigation:** Acceptable side effect, provides LRU-like behavior
  - **Mitigation:** Active collections stay cached longer (desirable)

- **Lock acquisition failure risk:** Cache update may fail
  - **Mitigation:** Graceful degradation - API update still succeeds
  - **Mitigation:** Cache becomes consistent when TTL expires
  - **Mitigation:** Log warnings for monitoring

## Implementation Guidelines

### Generic Cache Update Pattern

Use TypeVar for type-safe generic cache updates:

```python
T = TypeVar("T", bound=BaseModel)

def _update_cached_dict(
    self,
    cache_key: str,
    obj_id: str,
    obj: T,
    ttl: int,
) -> None:
    """Update single object in cached dict with distributed lock.

    Args:
        cache_key: Cache key for the collection
        obj_id: ID of object to update
        obj: Updated object
        ttl: Time-to-live in seconds

    Note:
        - Acquires distributed lock for thread safety
        - Only updates if cache exists (doesn't create partial cache)
        - Extends TTL for entire cached collection
        - Logs warning if lock acquisition fails
    """
    try:
        with self.cache.lock(cache_key):
            # Get current cached collection
            cached = self._get_cached_dict(cache_key, type(obj))

            # Update only if cache exists
            if cached:
                cached[obj_id] = obj
                self._set_cached_dict(cache_key, cached, ttl)

    except RuntimeError as e:
        logger.warning(f"Could not acquire lock for {cache_key}: {e}")
        # Update failed, but API call succeeded
        # Cache becomes eventually consistent via TTL expiration
```

### Usage in Workspace Client

```python
class WorkspaceClient:
    """Cache + compute layer."""

    def update_resource(
        self,
        resource_id: str,
        **kwargs,
    ) -> Resource:
        """Update resource and cache (O(1) update, not invalidation)."""
        # 1. Update via API (Layer 1)
        updated = self.api_client.update_resource(resource_id, **kwargs)

        # 2. Update cache (O(1), not invalidation)
        self._update_cached_dict(
            self._cache_key_resources(),
            resource_id,
            updated,
            self.settings.cache_ttl,
        )

        return updated

    def delete_resource(self, resource_id: str) -> None:
        """Delete resource and update cache."""
        # 1. Delete via API
        self.api_client.delete_resource(resource_id)

        # 2. Remove from cache
        try:
            with self.cache.lock(cache_key):
                cached = self._get_cached_dict(cache_key, Resource)
                if cached:
                    cached.pop(resource_id, None)
                    self._set_cached_dict(cache_key, cached, ttl)
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock: {e}")

    def create_resource(self, **kwargs) -> Resource:
        """Create resource and update cache."""
        # 1. Create via API
        created = self.api_client.create_resource(**kwargs)

        # 2. Add to cache
        try:
            with self.cache.lock(cache_key):
                cached = self._get_cached_dict(cache_key, Resource)
                if cached:
                    cached[created.id] = created
                    self._set_cached_dict(cache_key, cached, ttl)
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock: {e}")

        return created
```

### When to Use Cache Update

**Use cache update when:**

- Single resource modifications (update, delete, create one resource)
- High read-to-write ratio (many reads between writes)
- Stable schema (resource structure doesn't change)
- Independent resources (no complex dependencies between collections)

**Use cache invalidation instead when:**

- Bulk operations (updating 100+ resources at once)
- Complex dependencies (update affects multiple cached collections)
- Schema changes (resource structure changes)
- Simpler to invalidate than update each item

### Performance Metrics

Expected improvements in production:

**API Call Reduction:**

- Before: Several API calls per update (update + refetch)
- After: 1 API call per update (update only)
- Savings: Reduction of API calls

**Latency Improvement:**

- Before: 100-500ms for next read (API call)
- After: 1-5ms for next read (cache hit)
- Improvement: 20-100x faster

**Rate Limit Usage:**

- Before: Consumes 2 rate limit slots per update
- After: Consumes 1 rate limit slot per update
- Result: 2x more capacity for other operations

## References

- Related ADRs: ADR-013 (Distributed Cache Locking), ADR-014 (Three-Layer Architecture)
- Pattern: Double-check locking for cache reads
- Implementation: Generic `_update_cached_dict()` helper with TypeVar in `qontract_api/integrations/slack_usergroups/slack_workspace_client.py`
- Cache Backend: `qontract_api/qontract_api/cache/base.py`

---

## Notes

**Example: Slack API Integration**

This strategy was first implemented for the Slack API integration where usergroup updates are common:

**Before (Cache Invalidation):**

```python
def update_usergroup(self, usergroup_id: str, **kwargs):
    updated = self.slack_api.usergroups_update(usergroup_id, **kwargs)
    self.cache.delete("slack:workspace:usergroups")  # Invalidate
    return updated
# Next read: Fetch all 50+ usergroups via API (200-500ms)
```

**After (Cache Update):**

```python
def update_usergroup(self, usergroup_id: str, **kwargs):
    updated = self.slack_api.usergroups_update(usergroup_id, **kwargs)
    self._update_cached_dict(
        "slack:workspace:usergroups",
        usergroup_id,
        updated,
        self.settings.slack.usergroup_cache_ttl,
    )
    return updated
# Next read: Cache hit (1-5ms)
```

**Impact:**

- Reduced API calls from 2 to 1 per update
- Next read latency: 200-500ms → 1-5ms (100x improvement)
- More capacity for other Slack API operations

**Monitoring:**

Track these metrics to validate effectiveness:

```python
# Cache hit rate (should increase with updates)
cache_hit_rate = cache_hits / (cache_hits + cache_misses)

# API call reduction (should decrease)
api_calls_saved = invalidations_avoided * avg_collection_size

# Lock acquisition success rate (should be > 99%)
lock_success_rate = successful_locks / total_lock_attempts
```
