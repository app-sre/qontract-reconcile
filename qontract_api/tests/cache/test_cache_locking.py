"""Unit tests for distributed cache locking."""

# ruff: noqa: ARG002, SIM117, PT011

from collections.abc import Generator
from contextlib import contextmanager

import pytest

from qontract_api.cache.base import CacheBackend


class MockCacheBackend(CacheBackend):
    """Mock cache backend for testing lock functionality."""

    def __init__(self) -> None:
        """Initialize mock cache."""
        super().__init__()
        self.storage: dict[str, str] = {}
        self.locks: dict[str, bool] = {}

    def get(self, key: str) -> str | None:
        """Get value from mock storage."""
        return self.storage.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set value in mock storage."""
        self.storage[key] = value

    def _delete_from_backend(self, key: str) -> None:
        """Delete key from mock backend storage."""
        self.storage.pop(key, None)

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return key in self.storage

    def ping(self) -> bool:
        """Always returns True for mock."""
        return True

    def close(self) -> None:
        """Clear mock storage."""
        self.storage.clear()
        self.locks.clear()

    @contextmanager
    def lock(self, key: str, timeout: float = 300) -> Generator[None, None, None]:
        """Acquire distributed lock (mock implementation)."""
        lock_key = f"{key}:lock"
        if lock_key in self.locks:
            msg = f"Could not acquire lock for {key}"
            raise RuntimeError(msg)

        self.locks[lock_key] = True
        try:
            yield
        finally:
            self.locks.pop(lock_key, None)


def test_lock_context_manager_acquires_and_releases_lock() -> None:
    """Test that lock context manager acquires and releases lock correctly."""
    cache = MockCacheBackend()

    with cache.lock("test_key"):
        # Lock should be acquired
        assert "test_key:lock" in cache.locks

    # Lock should be released after context
    assert "test_key:lock" not in cache.locks


def test_lock_raises_runtime_error_if_cannot_acquire() -> None:
    """Test that lock raises RuntimeError if lock cannot be acquired."""
    cache = MockCacheBackend()

    # Manually acquire lock
    cache.locks["test_key:lock"] = True

    with pytest.raises(RuntimeError, match="Could not acquire lock for test_key"):
        with cache.lock("test_key", timeout=0.1):
            pass


def test_lock_releases_on_exception() -> None:
    """Test that lock is released even if exception occurs in context."""
    cache = MockCacheBackend()

    with pytest.raises(ValueError), cache.lock("test_key"):
        assert "test_key:lock" in cache.locks
        raise ValueError("Test error")

    # Lock should still be released
    assert "test_key:lock" not in cache.locks


def test_lock_appends_lock_suffix() -> None:
    """Test that lock appends :lock suffix to key."""
    cache = MockCacheBackend()

    with cache.lock("my_cache_key"):
        assert "my_cache_key:lock" in cache.locks
        assert "my_cache_key" not in cache.locks


def test_multiple_locks_on_different_keys() -> None:
    """Test that multiple locks on different keys work independently."""
    cache = MockCacheBackend()

    with cache.lock("key1"):
        assert "key1:lock" in cache.locks

        with cache.lock("key2"):
            assert "key1:lock" in cache.locks
            assert "key2:lock" in cache.locks

        assert "key2:lock" not in cache.locks
        assert "key1:lock" in cache.locks

    assert "key1:lock" not in cache.locks


# NOTE: Tests for lock timeout parameters removed - lock() is now abstract
# and each backend implements its own locking mechanism (e.g., valkey.lock()
# for Redis, conditional writes for DynamoDB, etc.)
