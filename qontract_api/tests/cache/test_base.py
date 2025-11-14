"""Unit tests for CacheBackend abstract base class."""

import json
from collections.abc import Callable
from typing import Any

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

    def ping(self) -> bool:  # noqa: PLR6301
        """Always returns True for in-memory cache."""
        return True

    def close(self) -> None:
        """Clear storage on close."""
        self.storage.clear()

    def _acquire_lock(self, lock_key: str, timeout: int) -> bool:  # noqa: ARG002
        """Acquire lock (in-memory, always succeeds)."""
        if lock_key in self.storage:
            return False
        self.storage[lock_key] = "1"
        return True

    def _release_lock(self, lock_key: str) -> None:
        """Release lock (in-memory)."""
        self.storage.pop(lock_key, None)


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
