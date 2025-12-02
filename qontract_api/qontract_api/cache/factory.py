"""Cache backend factory for workers.

Provides singleton cache instance shared across all workers and tasks.
Uses CacheBackend.get_instance() factory pattern.
"""

from redis import Redis

from qontract_api.cache.base import CacheBackend
from qontract_api.config import settings


def get_cache() -> CacheBackend:
    """Get singleton cache instance based on settings.cache_backend.

    Uses CacheBackend.get_instance() factory which provides:
    - Thread-safe singleton per backend type
    - Shared in-memory cache across all tasks in worker process
    - Support for multiple backend types (redis, dynamodb, etc.)

    Returns:
        Singleton CacheBackend instance for configured backend type

    Raises:
        ValueError: If settings.cache_backend is not supported

    Example:
        @celery_app.task
        def my_task():
            cache = get_cache()  # Same instance across all tasks
            cache.set("key", "value")
    """
    if settings.cache_backend == "redis":
        client = Redis.from_url(
            settings.cache_broker_url,
            encoding="utf-8",
            decode_responses=True,
        )
        return CacheBackend.get_instance(
            backend_type="redis",
            client=client,
            memory_max_size=settings.cache_memory_max_size,
            memory_ttl=settings.cache_memory_ttl,
        )
    msg = f"Unsupported cache backend: {settings.cache_backend}"
    raise ValueError(msg)
