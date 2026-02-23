"""Redis/Valkey cache backend implementation."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

from qontract_api.cache.base import CacheBackend

if TYPE_CHECKING:
    from redis import Redis


class RedisCacheBackend(CacheBackend):
    """Redis/Valkey cache backend with two-tier caching (synchronous).

    Two-Tier Cache (ADR-016):
    - Tier 1: In-memory LRU cache (Python objects, no serialization)
    - Tier 2: Redis/Valkey (JSON strings, persistent/shared)

    Stores values as strings. Caller is responsible for serialization/deserialization.
    """

    def __init__(
        self,
        client: Redis,
        serializer: Callable[[Any], str] | None = None,
        deserializer: Callable[[str], Any] | None = None,
        memory_max_size: int = 1000,
        memory_ttl: int = 60,
    ) -> None:
        """Initialize Redis/Valkey cache backend with two-tier caching.

        Args:
            redis_client: Synchronous Valkey/Redis client
            serializer: Function to serialize objects to strings (default: json_dumps)
            deserializer: Function to deserialize strings to objects (default: json_loads)
            memory_max_size: Max items in memory cache (LRU eviction). 0 = disabled.
            memory_ttl: Memory cache TTL in seconds
        """
        super().__init__(
            serializer=serializer,
            deserializer=deserializer,
            memory_max_size=memory_max_size,
            memory_ttl=memory_ttl,
        )
        self._client = client

    def get(self, key: str) -> str | None:
        """Get value from cache as string.

        Args:
            key: Cache key

        Returns:
            Cached string value or None if key doesn't exist
        """
        value = self.client.get(key)
        return str(value) if value else None

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set string value in cache with optional TTL.

        Args:
            key: Cache key
            value: String value to cache
            ttl: Time-to-live in seconds (None = no expiration)
        """
        if ttl:
            self.client.setex(key, ttl, value)
        else:
            self.client.set(key, value)

    def _delete_from_backend(self, key: str) -> None:
        """Delete key from Redis backend storage.

        Args:
            key: Cache key to delete
        """
        self.client.delete(key)

    def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists, False otherwise
        """
        return bool(self.client.exists(key))

    def ping(self) -> bool:
        """Check if Redis/Valkey is reachable.

        Returns:
            True if cache is reachable, False otherwise
        """
        try:
            self.client.ping()
            return True
        except OSError:
            # Network/connection errors
            return False

    def close(self) -> None:
        """Close Redis connection.

        Note: Synchronous redis client uses connection pool which is
        closed automatically. Explicit close for cleanup.
        """
        self.client.close()

    @property
    def client(self) -> Redis:
        """Return the underlying Redis client."""
        return self._client

    @contextmanager
    def lock(self, key: str, timeout: float = 300) -> Generator[None, None, None]:
        """Distributed lock using Valkey's native lock (Lua scripts + watch-dog).

        Uses valkey.lock() which provides:
        - Atomic lock acquisition via Lua scripts
        - Automatic renewal (watch-dog pattern)
        - Thread-safe by design
        - Non-blocking mode support

        Args:
            key: Lock key
            timeout: Lock timeout in seconds

        Yields:
            None (lock is acquired)

        Raises:
            RuntimeError: If lock could not be acquired
        """
        lock_key = f"{key}:lock"
        lock = self.client.lock(lock_key, timeout=timeout, blocking=True)

        if not lock.acquire():
            msg = f"Could not acquire lock for {key}"
            raise RuntimeError(msg)

        try:
            yield
        finally:
            # Lock may have expired - ignore release errors
            with suppress(Exception):
                lock.release()
