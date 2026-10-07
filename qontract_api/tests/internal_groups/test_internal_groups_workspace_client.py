"""Unit tests for InternalGroupsWorkspaceClient (caching + locking)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.internal_groups_api import Group

from qontract_api.cache.base import CacheBackend
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
    m.get_obj.return_value = None
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
    mock_cache.get_obj.return_value = cached

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
    """Second get_obj call (inside lock) returns data -> API must not be called."""
    cached = CachedGroup(group=_group())
    mock_cache.get_obj.side_effect = [None, cached]

    with client:
        result = client.get_group(GROUP_NAME)

    assert result == cached.group
    mock_api.group.assert_not_called()
    mock_cache.set_obj.assert_not_called()
