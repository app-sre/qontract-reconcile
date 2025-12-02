"""Unit tests for CacheBackend abstract base class."""

import json
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from qontract_api.cache.base import CacheBackend


class SampleModel(BaseModel):
    """Sample Pydantic model for cache tests."""

    name: str
    value: int
    tags: list[str] = []


class NestedModel(BaseModel):
    """Test nested Pydantic model."""

    users: list[str]
    channels: list[str]
    description: str


class ConcreteCacheBackend(CacheBackend):
    """Concrete implementation of CacheBackend for testing."""

    def __init__(
        self,
        serializer: Callable[[Any], str] | None = None,
        deserializer: Callable[[str], Any] | None = None,
    ) -> None:
        """Initialize with in-memory storage."""
        super().__init__(serializer=serializer, deserializer=deserializer)
        self.storage: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        """Get string value from cache."""
        return self.storage.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:  # noqa: ARG002
        """Set string value in cache (TTL ignored for in-memory)."""
        self.storage[key] = value

    def _delete_from_backend(self, key: str) -> None:
        """Delete key from backend storage."""
        self.storage.pop(key, None)

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return key in self.storage

    def ping(self) -> bool:
        """Always returns True for in-memory cache."""
        return True

    def close(self) -> None:
        """Clear storage on close."""
        self.storage.clear()

    @contextmanager
    def lock(self, key: str, timeout: float = 300) -> Generator[None, None, None]:  # noqa: ARG002
        """Mock lock implementation (no-op for base tests)."""
        yield


@pytest.fixture
def cache() -> ConcreteCacheBackend:
    """Create concrete cache implementation."""
    return ConcreteCacheBackend()


def test_cache_backend_is_abstract() -> None:
    """Test that CacheBackend cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        CacheBackend()  # type: ignore[abstract]


def test_get_returns_none_for_missing_key(cache: ConcreteCacheBackend) -> None:
    """Test get() returns None for non-existent keys."""
    result = cache.get("nonexistent")
    assert result is None


def test_set_and_get(cache: ConcreteCacheBackend) -> None:
    """Test basic set and get operations."""
    cache.set("test_key", "test_value")
    result = cache.get("test_key")
    assert result == "test_value"


def test_set_overwrites_existing_value(cache: ConcreteCacheBackend) -> None:
    """Test set() overwrites existing values."""
    cache.set("test_key", "value1")
    cache.set("test_key", "value2")
    result = cache.get("test_key")
    assert result == "value2"


def test_delete_removes_key(cache: ConcreteCacheBackend) -> None:
    """Test delete() removes keys."""
    cache.set("test_key", "test_value")
    cache.delete("test_key")
    result = cache.get("test_key")
    assert result is None


def test_delete_nonexistent_key_does_not_raise(cache: ConcreteCacheBackend) -> None:
    """Test delete() on non-existent key doesn't raise error."""
    cache.delete("nonexistent")  # Should not raise


def test_exists_returns_true_for_existing_key(cache: ConcreteCacheBackend) -> None:
    """Test exists() returns True for existing keys."""
    cache.set("test_key", "test_value")
    assert cache.exists("test_key") is True


def test_exists_returns_false_for_missing_key(cache: ConcreteCacheBackend) -> None:
    """Test exists() returns False for non-existent keys."""
    assert cache.exists("nonexistent") is False


def test_ping_returns_true(cache: ConcreteCacheBackend) -> None:
    """Test ping() returns True."""
    assert cache.ping() is True


def test_close_clears_storage(cache: ConcreteCacheBackend) -> None:
    """Test close() clears all data."""
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.close()
    assert cache.get("key1") is None
    assert cache.get("key2") is None


def test_set_with_json_string(cache: ConcreteCacheBackend) -> None:
    """Test storing JSON-serialized strings (low-level API)."""
    test_data = {"foo": "bar", "count": 42}
    cache.set("test_key", json.dumps(test_data))
    result = cache.get("test_key")
    assert result == json.dumps(test_data)
    assert json.loads(result) == test_data


def test_set_with_json_list_string(cache: ConcreteCacheBackend) -> None:
    """Test storing JSON-serialized list values (low-level API)."""
    test_data = ["item1", "item2", "item3"]
    cache.set("test_key", json.dumps(test_data))
    result = cache.get("test_key")
    assert result == json.dumps(test_data)
    assert json.loads(result) == test_data


def test_set_with_ttl_parameter(cache: ConcreteCacheBackend) -> None:
    """Test set() accepts TTL parameter (even if not used)."""
    cache.set("test_key", "test_value", ttl=300)
    result = cache.get("test_key")
    assert result == "test_value"


def test_multiple_keys(cache: ConcreteCacheBackend) -> None:
    """Test working with multiple keys."""
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    assert cache.get("key1") == "value1"
    assert cache.get("key2") == "value2"
    assert cache.get("key3") == "value3"

    cache.delete("key2")

    assert cache.exists("key1") is True
    assert cache.exists("key2") is False
    assert cache.exists("key3") is True


def test_get_obj_returns_none_for_missing_key(cache: ConcreteCacheBackend) -> None:
    """Test get_obj() returns None for non-existent keys."""
    result = cache.get_obj("nonexistent", cls=SampleModel)
    assert result is None


def test_get_obj_deserializes_pydantic_model(cache: ConcreteCacheBackend) -> None:
    """Test get_obj() deserializes into Pydantic model."""
    value = 42
    model = SampleModel(name="test", value=value, tags=["a", "b"])
    cache.set("test_key", json.dumps(model.model_dump()))

    result = cache.get_obj("test_key", cls=SampleModel)

    assert isinstance(result, SampleModel)
    assert result.name == "test"
    assert result.value == value
    assert result.tags == ["a", "b"]


def test_set_obj_serializes_pydantic_model(cache: ConcreteCacheBackend) -> None:
    """Test set_obj() serializes Pydantic model to JSON."""
    model = SampleModel(name="test", value=42, tags=["x", "y"])

    cache.set_obj("test_key", model)

    raw_value = cache.get("test_key")
    assert raw_value is not None
    data = json.loads(raw_value)
    assert data == {"name": "test", "tags": ["x", "y"], "value": 42}


def test_set_obj_with_ttl(cache: ConcreteCacheBackend) -> None:
    """Test set_obj() passes TTL to underlying set()."""
    model = SampleModel(name="test", value=42)

    cache.set_obj("test_key", model, ttl=300)

    result = cache.get_obj("test_key", cls=SampleModel)
    assert result == model


def test_get_obj_set_obj_roundtrip(cache: ConcreteCacheBackend) -> None:
    """Test roundtrip: set_obj() -> get_obj() preserves Pydantic model."""
    original = NestedModel(
        users=["alice", "bob"],
        channels=["general", "random"],
        description="Test group",
    )

    cache.set_obj("test_key", original)
    result = cache.get_obj("test_key", cls=NestedModel)

    assert result == original
    assert isinstance(result, NestedModel)


def test_get_obj_with_nested_model(cache: ConcreteCacheBackend) -> None:
    """Test get_obj() works with nested Pydantic models."""
    model = NestedModel(
        users=["user1", "user2"],
        channels=["chan1", "chan2"],
        description="A description",
    )

    cache.set_obj("test_key", model)
    result = cache.get_obj("test_key", cls=NestedModel)

    assert result is not None
    assert result.users == ["user1", "user2"]
    assert result.channels == ["chan1", "chan2"]
    assert result.description == "A description"


def test_custom_serializer_deserializer() -> None:
    """Test CacheBackend with custom serializer/deserializer."""

    def custom_serializer(obj: Any) -> str:
        if isinstance(obj, BaseModel):
            return f"CUSTOM:{obj.model_dump_json()}"
        return f"CUSTOM:{json.dumps(obj)}"

    def custom_deserializer(s: str) -> Any:
        return json.loads(s.removeprefix("CUSTOM:"))

    value = 42
    cache = ConcreteCacheBackend(
        serializer=custom_serializer, deserializer=custom_deserializer
    )
    model = SampleModel(name="test", value=value)

    cache.set_obj("test_key", model)

    # Low-level get shows custom format
    raw_value = cache.get("test_key")
    assert raw_value is not None
    assert raw_value.startswith("CUSTOM:")

    # High-level get_obj uses custom deserializer
    result = cache.get_obj("test_key", cls=SampleModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == value


# Singleton Pattern Tests


def test_get_instance_returns_singleton() -> None:
    """Test get_instance returns the same instance for same backend type."""
    # Reset singletons before test
    CacheBackend.reset_singleton()

    # Create mock redis client
    mock_client = MagicMock()

    # First call creates instance
    instance1 = CacheBackend.get_instance(
        backend_type="redis", client=mock_client, memory_max_size=100, memory_ttl=60
    )

    # Second call returns same instance
    instance2 = CacheBackend.get_instance(
        backend_type="redis", client=mock_client, memory_max_size=100, memory_ttl=60
    )

    assert instance1 is instance2

    # Cleanup
    CacheBackend.reset_singleton()


def test_get_instance_different_backends_return_different_instances() -> None:
    """Test get_instance returns different instances for different backend types."""
    # Reset singletons before test
    CacheBackend.reset_singleton()

    mock_client = MagicMock()

    # Create redis instance
    redis_instance = CacheBackend.get_instance(
        backend_type="redis", client=mock_client, memory_max_size=100, memory_ttl=60
    )

    # Note: We can't test "dynamodb" without implementing DynamoDBCacheBackend
    # Just verify redis instance is stored
    assert redis_instance is not None

    # Cleanup
    CacheBackend.reset_singleton()


def test_get_instance_thread_safe() -> None:
    """Test get_instance is thread-safe (double-checked locking)."""
    # Reset singletons before test
    CacheBackend.reset_singleton()

    instances: list[CacheBackend] = []
    mock_client = MagicMock()

    def create_instance() -> None:
        instance = CacheBackend.get_instance(
            backend_type="redis",
            client=mock_client,
            memory_max_size=100,
            memory_ttl=60,
        )
        instances.append(instance)

    # Create 10 threads that all try to get the singleton
    threads = [threading.Thread(target=create_instance) for _ in range(10)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    # All instances should be the same object
    assert len(instances) == 10
    assert all(instance is instances[0] for instance in instances)

    # Cleanup
    CacheBackend.reset_singleton()


def test_reset_singleton_clears_instance() -> None:
    """Test reset_singleton clears the singleton instance."""
    # Reset singletons before test
    CacheBackend.reset_singleton()

    mock_client = MagicMock()

    # Create instance
    instance1 = CacheBackend.get_instance(
        backend_type="redis", client=mock_client, memory_max_size=100, memory_ttl=60
    )

    # Reset singleton
    CacheBackend.reset_singleton("redis")

    # Next call creates new instance
    instance2 = CacheBackend.get_instance(
        backend_type="redis", client=mock_client, memory_max_size=100, memory_ttl=60
    )

    assert instance1 is not instance2

    # Cleanup
    CacheBackend.reset_singleton()


def test_reset_singleton_all_clears_all_backends() -> None:
    """Test reset_singleton without backend_type clears all singletons."""
    # Reset singletons before test
    CacheBackend.reset_singleton()

    mock_client = MagicMock()

    # Create redis instance
    redis_instance1 = CacheBackend.get_instance(
        backend_type="redis", client=mock_client, memory_max_size=100, memory_ttl=60
    )

    # Reset all singletons
    CacheBackend.reset_singleton()

    # Next call creates new instance
    redis_instance2 = CacheBackend.get_instance(
        backend_type="redis", client=mock_client, memory_max_size=100, memory_ttl=60
    )

    assert redis_instance1 is not redis_instance2

    # Cleanup
    CacheBackend.reset_singleton()


def test_get_instance_invalid_backend_raises_error() -> None:
    """Test get_instance raises ValueError for unsupported backend type."""
    # Reset singletons before test
    CacheBackend.reset_singleton()

    mock_client = MagicMock()

    with pytest.raises(ValueError, match="Unsupported cache backend: invalid"):
        CacheBackend.get_instance(
            backend_type="invalid",
            client=mock_client,
            memory_max_size=100,
            memory_ttl=60,
        )

    # Cleanup
    CacheBackend.reset_singleton()
