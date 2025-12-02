"""Unit tests for RedisCacheBackend."""

import json
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from qontract_api.cache.redis import RedisCacheBackend


class SampleModel(BaseModel):
    """Test Pydantic model for cache tests."""

    name: str
    value: int
    tags: list[str] = []


class NestedModel(BaseModel):
    """Test nested Pydantic model."""

    users: list[str]
    channels: list[str]
    description: str


@pytest.fixture
def mock_redis_client() -> Mock:
    """Create a mock Redis/Valkey client."""
    return Mock()


@pytest.fixture
def cache(mock_redis_client: Mock) -> RedisCacheBackend:
    """Create RedisCacheBackend with mock client."""
    return RedisCacheBackend(mock_redis_client)


def test_get_returns_none_when_key_not_found(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test get() returns None when key doesn't exist."""
    mock_redis_client.get.return_value = None

    result = cache.get("nonexistent_key")

    assert result is None
    mock_redis_client.get.assert_called_once_with("nonexistent_key")


def test_get_returns_string_value(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test get() returns string values."""
    mock_redis_client.get.return_value = "test_value"

    result = cache.get("test_key")

    assert result == "test_value"
    mock_redis_client.get.assert_called_once_with("test_key")


def test_get_returns_empty_string_as_none(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test get() treats empty string as None."""
    mock_redis_client.get.return_value = ""

    result = cache.get("test_key")

    assert result is None


def test_set_stores_string_value(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test set() stores string values."""
    cache.set("test_key", "test_value")

    mock_redis_client.set.assert_called_once_with("test_key", "test_value")


def test_set_with_ttl_uses_setex(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test set() with TTL uses setex."""
    ttl = 300

    cache.set("test_key", "test_value", ttl=ttl)

    mock_redis_client.setex.assert_called_once_with("test_key", ttl, "test_value")
    mock_redis_client.set.assert_not_called()


def test_delete_calls_redis_delete(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test delete() calls Redis delete."""
    cache.delete("test_key")

    mock_redis_client.delete.assert_called_once_with("test_key")


def test_exists_returns_true_when_key_exists(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test exists() returns True when key exists."""
    mock_redis_client.exists.return_value = 1

    result = cache.exists("test_key")

    assert result is True
    mock_redis_client.exists.assert_called_once_with("test_key")


def test_exists_returns_false_when_key_not_found(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test exists() returns False when key doesn't exist."""
    mock_redis_client.exists.return_value = 0

    result = cache.exists("test_key")

    assert result is False


def test_ping_returns_true_on_success(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test ping() returns True on success."""
    mock_redis_client.ping.return_value = True

    result = cache.ping()

    assert result is True
    mock_redis_client.ping.assert_called_once()


def test_ping_returns_false_on_connection_error(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test ping() returns False on connection error."""
    mock_redis_client.ping.side_effect = OSError("Connection error")

    result = cache.ping()

    assert result is False


def test_close_calls_redis_close(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test close() calls Redis close."""
    cache.close()

    mock_redis_client.close.assert_called_once()


def test_get_with_json_string(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test get() returns JSON strings as-is (caller deserializes)."""
    json_str = '{"foo": "bar", "count": 42}'
    mock_redis_client.get.return_value = json_str

    result = cache.get("test_key")

    assert result == json_str


def test_set_with_json_string(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test set() stores JSON strings (caller serializes)."""
    json_str = '["item1", "item2"]'

    cache.set("test_key", json_str)

    mock_redis_client.set.assert_called_once_with("test_key", json_str)


def test_set_without_ttl(cache: RedisCacheBackend, mock_redis_client: Mock) -> None:
    """Test set() without TTL uses set."""
    cache.set("test_key", "test_value")

    mock_redis_client.set.assert_called_once_with("test_key", "test_value")
    mock_redis_client.setex.assert_not_called()


def test_multiple_operations(cache: RedisCacheBackend, mock_redis_client: Mock) -> None:
    """Test working with multiple keys."""
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    mock_redis_client.exists.return_value = 1

    assert cache.exists("key1") is True
    cache.delete("key1")

    assert mock_redis_client.delete.called


def test_get_obj_returns_none_for_missing_key(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test get_obj() returns None when key doesn't exist."""
    mock_redis_client.get.return_value = None

    result = cache.get_obj("nonexistent", cls=SampleModel)

    assert result is None


def test_get_obj_deserializes_pydantic_model(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test get_obj() deserializes into Pydantic model."""
    model = SampleModel(name="test", value=42, tags=["a", "b"])
    mock_redis_client.get.return_value = json.dumps(model.model_dump())

    result = cache.get_obj("test_key", cls=SampleModel)

    assert isinstance(result, SampleModel)
    assert result.name == "test"
    assert result.value == 42
    assert result.tags == ["a", "b"]
    mock_redis_client.get.assert_called_once_with("test_key")


def test_get_obj_with_nested_model(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test get_obj() works with nested models."""
    model = NestedModel(
        users=["user1", "user2"],
        channels=["chan1"],
        description="Test",
    )
    mock_redis_client.get.return_value = json.dumps(model.model_dump())

    result = cache.get_obj("test_key", cls=NestedModel)

    assert isinstance(result, NestedModel)
    assert result.users == ["user1", "user2"]
    assert result.channels == ["chan1"]
    assert result.description == "Test"


def test_set_obj_serializes_pydantic_model(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test set_obj() serializes Pydantic model to JSON."""
    model = SampleModel(name="test", value=42, tags=["x", "y"])

    cache.set_obj("test_key", model)

    # Verify JSON was stored with sorted keys
    call_args = mock_redis_client.set.call_args
    stored_json = call_args[0][1]
    data = json.loads(stored_json)
    assert data == {"name": "test", "tags": ["x", "y"], "value": 42}


def test_set_obj_with_ttl(cache: RedisCacheBackend, mock_redis_client: Mock) -> None:
    """Test set_obj() with TTL passes to setex."""
    model = SampleModel(name="test", value=42)
    ttl = 300

    cache.set_obj("test_key", model, ttl=ttl)

    # Verify setex was called with serialized model
    call_args = mock_redis_client.setex.call_args
    assert call_args[0][0] == "test_key"
    assert call_args[0][1] == ttl
    stored_json = call_args[0][2]
    data = json.loads(stored_json)
    assert data == {"name": "test", "tags": [], "value": 42}


def test_get_obj_set_obj_roundtrip(
    cache: RedisCacheBackend, mock_redis_client: Mock
) -> None:
    """Test roundtrip: set_obj() -> get_obj() preserves Pydantic model."""
    original = NestedModel(
        users=["alice", "bob"],
        channels=["general", "random"],
        description="Test group",
    )

    cache.set_obj("test_key", original)

    # Simulate Redis returning the stored value
    call_args = mock_redis_client.set.call_args
    serialized = call_args[0][1]
    mock_redis_client.get.return_value = serialized

    result = cache.get_obj("test_key", cls=NestedModel)

    assert result == original
    assert isinstance(result, NestedModel)


def test_custom_serializer_deserializer() -> None:
    """Test RedisCacheBackend with custom serializer/deserializer."""
    mock_client = Mock()

    def custom_serializer(obj: Any) -> str:
        if isinstance(obj, BaseModel):
            return f"CUSTOM:{obj.model_dump_json()}"
        return f"CUSTOM:{json.dumps(obj)}"

    def custom_deserializer(s: str) -> Any:
        return json.loads(s.removeprefix("CUSTOM:"))

    cache = RedisCacheBackend(
        mock_client, serializer=custom_serializer, deserializer=custom_deserializer
    )

    model = SampleModel(name="test", value=42)
    cache.set_obj("test_key", model)

    # Verify custom serializer was used
    call_args = mock_client.set.call_args
    stored_value = call_args[0][1]
    assert stored_value.startswith("CUSTOM:")

    # Verify custom deserializer works
    mock_client.get.return_value = stored_value
    result = cache.get_obj("test_key", cls=SampleModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == 42
