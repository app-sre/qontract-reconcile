"""Unit tests for InternalGroupsWorkspaceClient (caching + locking)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest
from qontract_utils.internal_groups_api import Group
from qontract_utils.json_utils import json_dumps, json_loads

from qontract_api.cache.base import CacheBackend
from qontract_api.cache.redis import RedisCacheBackend
from qontract_api.config import Settings
from qontract_api.internal_groups.internal_groups_workspace_client import (
    CachedGroup,
    InternalGroupsWorkspaceClient,
)

if TYPE_CHECKING:
    from qontract_utils.internal_groups_api.api import InternalGroupsApi

ENV_KEY = "test-env-key"
GROUP_NAME = "team"
CACHE_KEY = f"internal_groups:{ENV_KEY}:group:{GROUP_NAME}"


@pytest.fixture
def mock_api() -> MagicMock:
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.get.return_value = None
    m.serializer = json_dumps
    m.deserializer = json_loads
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()


@pytest.fixture
def client(
    mock_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> InternalGroupsWorkspaceClient:
    def _factory() -> InternalGroupsApi:
        return mock_api

    return InternalGroupsWorkspaceClient(
        api_factory=_factory,
        cache=mock_cache,
        settings=mock_settings,
        environment_key=ENV_KEY,
    )


def _group(name: str = GROUP_NAME) -> Group:
    return Group(
        name=name,
        description="desc",
        contact_list="c@example.com",
        owners=[],
        display_name="Team",
    )


def _group_payload(name: str = GROUP_NAME) -> dict[str, object]:
    return {
        "name": name,
        "description": "desc",
        "contactList": "c@example.com",
        "owners": [],
        "displayName": "Team",
    }


def test_get_group_cache_hit_skips_api_call(
    client: InternalGroupsWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    cached = CachedGroup(group=_group())
    mock_cache.get.return_value = json_dumps(cached.model_dump())

    with client:
        result = client.get_group(GROUP_NAME)

    assert result == cached.group
    mock_api.group.assert_not_called()
    mock_cache.lock.assert_not_called()


def test_get_group_cache_miss_acquires_lock(
    client: InternalGroupsWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_api.group.return_value = _group_payload()

    with client:
        client.get_group(GROUP_NAME)

    mock_cache.lock.assert_called_once_with(CACHE_KEY)


def test_get_group_cache_miss_stores_result_with_configured_ttl(
    client: InternalGroupsWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_api.group.return_value = _group_payload()
    fetched = _group()

    with client:
        client.get_group(GROUP_NAME)

    mock_cache.set_obj.assert_called_once_with(
        CACHE_KEY,
        CachedGroup(group=fetched),
        ttl=mock_settings.internal_groups.group_cache_ttl,
    )


def test_get_group_double_check_inside_lock(
    client: InternalGroupsWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Shared-cache hit after lock -> API must not be called."""
    cached = CachedGroup(group=_group())
    serialized = json_dumps(cached.model_dump())

    def _get(key: str) -> str | None:
        if mock_cache.lock.call_count > 0:
            return serialized
        return None

    mock_cache.get.side_effect = _get

    with client:
        result = client.get_group(GROUP_NAME)

    assert result == cached.group
    mock_api.group.assert_not_called()
    mock_cache.set_obj.assert_not_called()


def _shared_redis_mock() -> tuple[Mock, dict[str, str]]:
    store: dict[str, str] = {}
    mock = Mock()

    def _get(key: str) -> str | None:
        return store.get(key)

    def _set(key: str, value: str) -> None:
        store[key] = value

    def _setex(key: str, _ttl: int, value: str) -> None:
        store[key] = value

    def _delete(key: str) -> None:
        store.pop(key, None)

    def _exists(key: str) -> bool:
        return key in store

    mock.get = _get
    mock.set = _set
    mock.setex = _setex
    mock.delete = _delete
    mock.exists = _exists
    mock.ping.return_value = True
    lock_mock = Mock()
    lock_mock.acquire.return_value = True
    lock_mock.release = Mock()
    mock.lock.return_value = lock_mock
    return mock, store


def test_get_group_shared_cache_not_stale_after_peer_invalidation(
    mock_settings: Settings,
) -> None:
    """Process-local L1 must not hide invalidation from another cache instance."""
    redis_mock, _store = _shared_redis_mock()
    cache_a = RedisCacheBackend(redis_mock, memory_max_size=100, memory_ttl=3600)
    cache_b = RedisCacheBackend(redis_mock, memory_max_size=100, memory_ttl=3600)

    api_a = MagicMock()
    api_a.__enter__ = MagicMock(return_value=api_a)
    api_a.__exit__ = MagicMock(return_value=False)
    api_b = MagicMock()
    api_b.__enter__ = MagicMock(return_value=api_b)
    api_b.__exit__ = MagicMock(return_value=False)

    client_a = InternalGroupsWorkspaceClient(
        api_factory=lambda: api_a,
        cache=cache_a,
        settings=mock_settings,
        environment_key=ENV_KEY,
    )
    client_b = InternalGroupsWorkspaceClient(
        api_factory=lambda: api_b,
        cache=cache_b,
        settings=mock_settings,
        environment_key=ENV_KEY,
    )

    stale_payload = _group_payload()
    fresh_payload = {**_group_payload(), "description": "updated"}
    api_a.group.return_value = stale_payload
    api_b.update_group.return_value = fresh_payload

    with client_a:
        first = client_a.get_group(GROUP_NAME)
    assert first is not None
    assert first.description == "desc"
    assert api_a.group.call_count == 1

    with client_b:
        client_b.update_group(_group())

    api_a.group.return_value = fresh_payload
    with client_a:
        second = client_a.get_group(GROUP_NAME)

    assert second is not None
    assert second.description == "updated"
    assert api_a.group.call_count == 2
