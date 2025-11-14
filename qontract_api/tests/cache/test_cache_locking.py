"""Unit tests for distributed cache locking."""

# ruff: noqa: ARG002, PLR6301, SIM117, PT012, PT011, SLF001

from unittest.mock import MagicMock

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

    def _acquire_lock(self, lock_key: str, timeout: int) -> bool:
        """Acquire lock (mock implementation)."""
        if lock_key in self.locks:
            return False
        self.locks[lock_key] = True
        return True

    def _release_lock(self, lock_key: str) -> None:
        """Release lock (mock implementation)."""
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
        with cache.lock("test_key"):
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


def test_lock_timeout_parameter() -> None:
    """Test that lock passes timeout to _acquire_lock."""
    cache = MockCacheBackend()
    cache._acquire_lock = MagicMock(return_value=True)  # type: ignore[method-assign]

    with cache.lock("test_key", timeout=30):
        pass

    cache._acquire_lock.assert_called_once_with("test_key:lock", 30)


def test_lock_default_timeout() -> None:
    """Test that lock uses default timeout of 10 seconds."""
    cache = MockCacheBackend()
    cache._acquire_lock = MagicMock(return_value=True)  # type: ignore[method-assign]

    with cache.lock("test_key"):
        pass

    cache._acquire_lock.assert_called_once_with("test_key:lock", 10)
