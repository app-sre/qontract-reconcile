"""Abstract cache backend interface with two-tier caching.

Follows ADR-005: Sync-Only Development
All methods are synchronous. FastAPI runs them in thread pool automatically.

Two-Tier Cache Architecture (ADR-016):
- Tier 1: In-memory LRU cache (Python objects, no serialization overhead)
- Tier 2: Redis/Valkey backend (JSON serialization for persistence)

Cache backends store string values. Callers are responsible for serialization/deserialization.

Singleton Pattern:
- CacheBackend.get_instance() provides thread-safe singleton per backend type
- Ensures in-memory cache is shared across all users in the same process
"""

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, ClassVar, TypeVar

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

    Singleton Pattern:
    - Use CacheBackend.get_instance() to get singleton instance per backend type
    - Thread-safe double-checked locking ensures only one instance per type
    """

    # Singleton instances per backend type (e.g., "redis", "dynamodb")
    _instances: ClassVar[dict[str, "CacheBackend"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get_instance(
        cls,
        backend_type: str,
        **kwargs: Any,
    ) -> "CacheBackend":
        """Get singleton cache instance for backend type (thread-safe factory).

        Uses double-checked locking for thread-safe singleton creation.
        Each backend type (redis, dynamodb, etc.) has its own singleton instance.

        Args:
            backend_type: Cache backend type ("redis", "dynamodb", etc.)
            **kwargs: Backend-specific initialization parameters
                     (e.g., client, memory_max_size, memory_ttl)

        Returns:
            Singleton CacheBackend instance for the specified backend type

        Raises:
            ValueError: If backend_type is not supported

        Example:
            from redis import Redis
            cache = CacheBackend.get_instance(
                backend_type="redis",
                client=Redis.from_url("redis://localhost"),
                memory_max_size=1000,
                memory_ttl=60,
            )
        """
        # Fast path: Check if instance exists (no lock needed)
        if backend_type in cls._instances:
            return cls._instances[backend_type]

        # Slow path: Create new instance (thread-safe)
        with cls._lock:
            # Double-check after acquiring lock
            if backend_type not in cls._instances:
                # Factory: Create backend based on type
                # Import moved inside to avoid circular imports
                if backend_type == "redis":
                    from qontract_api.cache.redis import (  # noqa: PLC0415
                        RedisCacheBackend,
                    )

                    cls._instances[backend_type] = RedisCacheBackend(**kwargs)
                else:
                    msg = f"Unsupported cache backend: {backend_type}"
                    raise ValueError(msg)

        return cls._instances[backend_type]

    @classmethod
    def reset_singleton(cls, backend_type: str | None = None) -> None:
        """Reset singleton instance(s) - primarily for testing.

        Args:
            backend_type: Specific backend type to reset (None = reset all)

        Example:
            # Reset all singletons
            CacheBackend.reset_singleton()

            # Reset only Redis singleton
            CacheBackend.reset_singleton("redis")
        """
        with cls._lock:
            if backend_type:
                # Reset specific backend
                if backend_type in cls._instances:
                    cls._instances[backend_type].close()
                    del cls._instances[backend_type]
            else:
                # Reset all backends
                for instance in cls._instances.values():
                    instance.close()
                cls._instances.clear()

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
        self._memory_cache: TTLCache[str, Any] | None = None

        # Tier 1: In-memory cache (Python objects, no serialization overhead)
        if memory_max_size > 0:
            self._memory_cache = TTLCache(
                maxsize=memory_max_size,
                ttl=memory_ttl,
            )

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

    @abstractmethod
    @contextmanager
    def lock(self, key: str, timeout: float = 300) -> Generator[None, None, None]:
        """Distributed lock context manager for thread-safe operations.

        Backend-specific implementation using native locking mechanisms:
        - Redis/Valkey: valkey.lock() with Lua scripts + watch-dog
        - DynamoDB: Conditional writes with version numbers
        - Firestore: Transactions with optimistic locking

        Args:
            key: Lock key (backend will add :lock suffix if needed)
            timeout: Lock timeout in seconds

        Yields:
            None (lock is acquired)

        Raises:
            RuntimeError: If lock could not be acquired

        Example:
            with cache.lock("my-resource", timeout=60):
                # Critical section - only one process at a time
                value = cache.get("my-resource")
                cache.set("my-resource", modified_value)
        """
        ...
