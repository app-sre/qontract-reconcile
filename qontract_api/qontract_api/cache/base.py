"""Abstract cache backend interface with two-tier caching.

Follows ADR-005: Sync-Only Development
All methods are synchronous. FastAPI runs them in thread pool automatically.

Two-Tier Cache Architecture (ADR-016):
- Tier 1: In-memory LRU cache (Python objects, no serialization overhead)
- Tier 2: Redis/Valkey backend (JSON serialization for persistence)

Cache backends store string values. Callers are responsible for serialization/deserialization.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, TypeVar

from cachetools import TTLCache
from pydantic import BaseModel
from qontract_utils.json_utils import json_dumps, json_loads

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class CacheBackend(ABC):
    """Abstract base class for cache backends with two-tier caching.

    Two-Tier Cache (ADR-016):
    - Tier 1 (memory): TTLCache - Python objects in memory (99% hit rate expected)
    - Tier 2 (persistent): Redis/Valkey - JSON strings for persistence/sharing

    All methods are synchronous following ADR-005 (Sync-Only).
    FastAPI automatically runs sync code in thread pool for non-blocking I/O.

    Cache stores string values only. Callers must handle serialization (e.g., JSON).
    """

    def __init__(
        self,
        serializer: Callable[[Any], str] | None = None,
        deserializer: Callable[[str], Any] | None = None,
        memory_max_size: int = 1000,
        memory_ttl: int = 60,
    ) -> None:
        """Initialize cache backend with two-tier caching.

        Args:
            serializer: Function to serialize objects to strings (default: json_dumps)
            deserializer: Function to deserialize strings to objects (default: json_loads)
            memory_max_size: Max items in memory cache (LRU eviction). 0 = disabled.
            memory_ttl: Memory cache TTL in seconds
        """
        self.serializer = serializer or json_dumps
        self.deserializer = deserializer or json_loads

        # Tier 1: In-memory cache (Python objects, no serialization overhead)
        if memory_max_size > 0:
            self._memory_cache: TTLCache[str, Any] | None = TTLCache(
                maxsize=memory_max_size,
                ttl=memory_ttl,
            )
        else:
            # Disabled memory cache (for testing or when not desired)
            self._memory_cache = None

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Get string value from cache.

        Args:
            key: Cache key

        Returns:
            Cached string value or None if key doesn't exist
        """
        ...

    @abstractmethod
    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set string value in cache with optional TTL.

        Args:
            key: Cache key
            value: String value to cache (caller must serialize complex types)
            ttl: Time-to-live in seconds (None = no expiration)
        """
        ...

    @abstractmethod
    def _delete_from_backend(self, key: str) -> None:
        """Delete key from backend storage (Redis/Valkey).

        Args:
            key: Cache key to delete
        """
        ...

    def delete(self, key: str) -> None:
        """Delete key from cache (both tiers: memory + Redis).

        Args:
            key: Cache key to delete
        """
        # Tier 1: Delete from memory cache
        if self._memory_cache is not None:
            self._memory_cache.pop(key, None)

        # Tier 2: Delete from Redis backend
        self._delete_from_backend(key)

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists, False otherwise
        """
        ...

    @abstractmethod
    def ping(self) -> bool:
        """Check if cache backend is reachable.

        Returns:
            True if cache is reachable, False otherwise
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Close cache connection and cleanup resources."""
        ...

    def clear_memory_cache(self) -> None:
        """Clear in-memory cache (Tier 1).

        Useful for testing or when you need to force refresh from Redis.
        Does not affect Redis cache (Tier 2).
        """
        if self._memory_cache is not None:
            self._memory_cache.clear()

    def get_obj(self, key: str, cls: type[T]) -> T | None:
        """Get object from cache with two-tier lookup (memory → Redis).

        Two-Tier Cache Lookup (ADR-016):
        1. Check memory cache (Tier 1) - instant, no deserialization
        2. Check Redis cache (Tier 2) - JSON deserialization, warms memory cache
        3. Return None if not found in either tier

        Args:
            key: Cache key
            cls: Pydantic BaseModel class to deserialize into

        Returns:
            Deserialized Pydantic model instance or None if key doesn't exist
        """
        # Tier 1: Memory cache (99% hit rate expected - FAST!)
        if self._memory_cache is not None and key in self._memory_cache:
            return self._memory_cache[key]

        # Tier 2: Redis/Valkey cache (JSON deserialization)
        try:
            value = self.get(key)
            if value is None:
                return None

            data = self.deserializer(value)
            obj = cls.model_validate(data)

            # Warm memory cache for next access
            if self._memory_cache is not None:
                self._memory_cache[key] = obj

            return obj

        except (ConnectionError, TimeoutError) as e:
            logger.warning(
                f"Cache backend unavailable, memory-only mode: {e}",
                extra={"cache_key": key},
            )
            return None

    def set_obj(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set object in cache (both tiers: memory + Redis).

        Two-Tier Cache Write (ADR-016):
        1. Write to memory cache (Tier 1) - instant
        2. Write to Redis cache (Tier 2) - JSON serialization, persistent

        Args:
            key: Cache key
            value: Object to cache (will be serialized for Redis)
            ttl: Time-to-live in seconds (None = no expiration)
        """
        # Tier 1: Memory cache (Python object, no serialization)
        if self._memory_cache is not None:
            self._memory_cache[key] = value

        # Tier 2: Redis cache (JSON serialization for persistence)
        try:
            serialized = self.serializer(value)
            self.set(key, serialized, ttl)
        except (ConnectionError, TimeoutError) as e:
            logger.warning(
                f"Cache backend unavailable, memory-only mode: {e}",
                extra={"cache_key": key},
            )

    @contextmanager
    def lock(self, key: str, timeout: int = 10) -> Generator[None, None, None]:
        """Distributed lock context manager for thread-safe cache updates.

        Args:
            key: Cache key to lock
            timeout: Lock timeout in seconds

        Yields:
            None (lock is acquired)

        Raises:
            RuntimeError: If lock could not be acquired within timeout
        """
        lock_key = f"{key}:lock"
        acquired = self._acquire_lock(lock_key, timeout)

        if not acquired:
            msg = f"Could not acquire lock for {key}"
            raise RuntimeError(msg)

        try:
            yield
        finally:
            self._release_lock(lock_key)

    @abstractmethod
    def _acquire_lock(self, lock_key: str, timeout: int) -> bool:
        """Acquire distributed lock.

        Args:
            lock_key: Lock key
            timeout: Lock timeout in seconds

        Returns:
            True if lock acquired, False otherwise
        """
        ...

    @abstractmethod
    def _release_lock(self, lock_key: str) -> None:
        """Release distributed lock.

        Args:
            lock_key: Lock key to release
        """
        ...
