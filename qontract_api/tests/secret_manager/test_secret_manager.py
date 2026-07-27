"""Tests for qontract_api.secret_manager.SecretManager."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel
from qontract_utils.secret_reader import SecretBackend

from qontract_api.cache.base import CacheBackend
from qontract_api.secret_manager import SecretManager


class FakeSecret(BaseModel):
    url: str = "https://vault.test"
    path: str = "secret/workspace-1/token"
    field: str | None = None
    version: int | None = None


class InMemoryCacheBackend(CacheBackend):
    """Minimal in-memory CacheBackend for SecretManager tests."""

    def __init__(self) -> None:
        super().__init__(memory_max_size=0)
        self.storage: dict[str, str] = {}
        self.lock_calls: list[str] = []

    def get(self, key: str) -> str | None:
        return self.storage.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:  # noqa: ARG002
        self.storage[key] = value

    def _delete_from_backend(self, key: str) -> None:
        self.storage.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.storage

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.storage.clear()

    @contextmanager
    def lock(self, key: str, timeout: float = 300) -> Generator[None]:  # noqa: ARG002
        self.lock_calls.append(key)
        yield


@pytest.fixture
def cache() -> InMemoryCacheBackend:
    return InMemoryCacheBackend()


@pytest.fixture
def backend() -> MagicMock:
    return MagicMock(spec=SecretBackend, url="https://vault.test")


@pytest.fixture
def manager(cache: InMemoryCacheBackend, backend: MagicMock) -> SecretManager:
    return SecretManager(cache=cache, secret_backends=[backend])


def test_write_calls_backend_and_invalidates_cache(
    manager: SecretManager, cache: InMemoryCacheBackend, backend: MagicMock
) -> None:
    secret = FakeSecret()
    cache_key = manager._cache_key(secret)
    cache.set(cache_key, "stale-value")

    manager.write(secret, {"token": "new-value"})

    backend.write.assert_called_once_with(secret, {"token": "new-value"}, force=False)
    assert cache.get(cache_key) is None
    assert cache_key in cache.lock_calls


def test_write_passes_force_flag(manager: SecretManager, backend: MagicMock) -> None:
    secret = FakeSecret()

    manager.write(secret, {"token": "new-value"}, force=True)

    backend.write.assert_called_once_with(secret, {"token": "new-value"}, force=True)


def test_write_does_not_invalidate_cache_on_backend_error(
    manager: SecretManager, cache: InMemoryCacheBackend, backend: MagicMock
) -> None:
    """A failed backend write must not clear a still-valid cache entry."""
    secret = FakeSecret()
    cache_key = manager._cache_key(secret)
    cache.set(cache_key, "stale-value")
    backend.write.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        manager.write(secret, {"token": "new-value"})

    assert cache.get(cache_key) == "stale-value"


def test_delete_calls_backend_and_invalidates_cache(
    manager: SecretManager, cache: InMemoryCacheBackend, backend: MagicMock
) -> None:
    secret = FakeSecret()
    cache_key = manager._cache_key(secret)
    cache.set(cache_key, "stale-value")

    manager.delete(secret)

    backend.delete.assert_called_once_with(secret)
    assert cache.get(cache_key) is None
    assert cache_key in cache.lock_calls


def test_delete_does_not_invalidate_cache_on_backend_error(
    manager: SecretManager, cache: InMemoryCacheBackend, backend: MagicMock
) -> None:
    secret = FakeSecret()
    cache_key = manager._cache_key(secret)
    cache.set(cache_key, "stale-value")
    backend.delete.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        manager.delete(secret)

    assert cache.get(cache_key) == "stale-value"


def test_list_calls_backend_and_bypasses_cache(
    manager: SecretManager, cache: InMemoryCacheBackend, backend: MagicMock
) -> None:
    secret = FakeSecret()
    backend.list.return_value = ["client-1", "client-2"]

    result = manager.list(secret)

    assert result == ["client-1", "client-2"]
    backend.list.assert_called_once_with(secret)
    assert cache.lock_calls == []
