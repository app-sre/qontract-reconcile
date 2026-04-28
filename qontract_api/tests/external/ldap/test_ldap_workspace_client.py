"""Tests for LdapWorkspaceClient (Layer 2 - caching + locking for direct LDAP)."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.ldap_api import LdapApi
from qontract_utils.ldap_api.models import LdapUser

from qontract_api.cache.base import CacheBackend
from qontract_api.config import LdapSettings, Settings
from qontract_api.external.ldap.ldap_workspace_client import (
    CachedUserCheck,
    LdapWorkspaceClient,
)
from qontract_api.external.ldap.schemas import LdapUserStatus


@pytest.fixture
def mock_api() -> MagicMock:
    """Create mock LdapApi."""
    return MagicMock(spec=LdapApi)


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock CacheBackend."""
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def ldap_settings() -> Settings:
    """Create test settings."""
    return Settings(ldap=LdapSettings(users_cache_ttl=300))


@pytest.fixture
def workspace_client(
    mock_api: MagicMock,
    mock_cache: MagicMock,
    ldap_settings: Settings,
) -> LdapWorkspaceClient:
    """Create LdapWorkspaceClient with mocked dependencies."""
    return LdapWorkspaceClient(
        api=mock_api,
        cache=mock_cache,
        settings=ldap_settings,
        cache_key_prefix="test-prefix",
    )


def test_check_users_exist_calls_api(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist delegates to LdapApi.get_users."""
    mock_api.get_users.return_value = [LdapUser(username="alice")]

    result = workspace_client.check_users_exist(["alice", "bob"])

    assert sorted(result, key=lambda u: u.username) == [
        LdapUserStatus(username="alice", exists=True),
        LdapUserStatus(username="bob", exists=False),
    ]
    mock_api.get_users.assert_called_once()


def test_check_users_exist_cache_hit(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist returns cached data on cache hit."""
    cached = CachedUserCheck(result=[LdapUserStatus(username="alice", exists=True)])
    mock_cache.get_obj.return_value = cached

    result = workspace_client.check_users_exist(["alice"])

    assert result == [LdapUserStatus(username="alice", exists=True)]
    mock_api.get_users.assert_not_called()


def test_check_users_exist_double_check_locking(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist uses double-check locking pattern."""
    # First get_obj returns None (cache miss), second returns cached data (after lock)
    cached = CachedUserCheck(result=[LdapUserStatus(username="alice", exists=True)])
    mock_cache.get_obj.side_effect = [None, cached]

    result = workspace_client.check_users_exist(["alice"])

    # Should return cached data without calling API
    assert result == [LdapUserStatus(username="alice", exists=True)]
    mock_api.get_users.assert_not_called()
    mock_cache.lock.assert_called_once()


def test_check_users_exist_acquires_lock_on_miss(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist acquires distributed lock on cache miss."""
    mock_api.get_users.return_value = []

    workspace_client.check_users_exist(["alice"])

    mock_cache.lock.assert_called_once()


def test_check_users_exist_caches_result(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
    ldap_settings: Settings,
) -> None:
    """Test check_users_exist stores result in cache with TTL."""
    mock_api.get_users.return_value = [LdapUser(username="alice")]

    workspace_client.check_users_exist(["alice", "bob"])

    mock_cache.set_obj.assert_called_once()
    call_args = mock_cache.set_obj.call_args
    assert call_args[1]["ttl"] == ldap_settings.ldap.users_cache_ttl


def test_check_users_exist_context_manager(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist uses LdapApi as context manager."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_users.return_value = []

    workspace_client.check_users_exist(["alice"])

    mock_api.__enter__.assert_called_once()
    mock_api.__exit__.assert_called_once()


def test_check_users_exist_empty_input(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test check_users_exist with empty input returns empty list."""
    result = workspace_client.check_users_exist([])

    assert result == []
    mock_api.get_users.assert_not_called()
    mock_cache.get_obj.assert_not_called()
