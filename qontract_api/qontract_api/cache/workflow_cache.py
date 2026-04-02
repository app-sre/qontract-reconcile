"""Workflow caching for idempotent task dispatch.

Prevents duplicate task execution by caching workflow IDs in Redis.
A workflow ID is typically a hash of the request parameters, and the
cached value is the Celery task_id (request_id) for status polling.
"""

from qontract_api.cache import CacheBackend

WORKFLOW_CACHE_PREFIX = "workflow"
WORKFLOW_CACHE_TTL = 86400  # 24 hours


def get_cached_task_id(cache: CacheBackend, workflow_id: str) -> str | None:
    """Return the cached Celery task_id for a workflow, or None if not cached."""
    return cache.get(f"{WORKFLOW_CACHE_PREFIX}:{workflow_id}")


def cache_workflow(cache: CacheBackend, workflow_id: str, *, task_id: str) -> None:
    """Cache workflow_id → task_id mapping."""
    cache.set(f"{WORKFLOW_CACHE_PREFIX}:{workflow_id}", task_id, WORKFLOW_CACHE_TTL)


def clear_workflow_cache(cache: CacheBackend, workflow_id: str) -> None:
    """Clear a workflow_id cache entry (e.g., on task failure)."""
    cache.delete(f"{WORKFLOW_CACHE_PREFIX}:{workflow_id}")
