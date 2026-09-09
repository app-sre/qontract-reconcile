"""Tests for LdapWorkspaceClient (Layer 2 - caching + locking for direct LDAP)."""

from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.ldap_api import LdapApi
from qontract_utils.ldap_api.models import LdapUser

from qontract_api.cache.base import CacheBackend
from qontract_api.config import LdapSettings, Settings
from qontract_api.external.ldap.ldap_workspace_client import (
    CachedGithubUsernames,
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


# --- resolve_github_usernames ---


def test_resolve_github_usernames_calls_api_and_matches(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames delegates to LdapApi and returns matches."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {
        "alicegh": ["alice"],
        "bob": ["bob"],
    }

    result = workspace_client.resolve_github_usernames(["AliceGH", "bob"])

    assert result == {"AliceGH": "alice", "bob": "bob"}
    mock_api.get_github_usernames.assert_called_once()


def test_resolve_github_usernames_case_insensitive(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames matches logins case-insensitively."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {"alicegh": ["alice"]}

    # Requested with different casing than stored in LDAP
    result = workspace_client.resolve_github_usernames(["alicegh"])

    # The requested login is echoed back (not the LDAP casing), mapped to uid
    assert result == {"alicegh": "alice"}


def test_resolve_github_usernames_omits_unresolved(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames omits logins not found in LDAP."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {"alicegh": ["alice"]}

    result = workspace_client.resolve_github_usernames(["AliceGH", "unknown"])

    assert result == {"AliceGH": "alice"}


def test_resolve_github_usernames_empty_input(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test resolve_github_usernames with empty input returns empty and skips work."""
    result = workspace_client.resolve_github_usernames([])

    assert result == {}
    mock_api.get_github_usernames.assert_not_called()
    mock_cache.get_obj.assert_not_called()


def test_resolve_github_usernames_cache_hit(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames serves the map from cache without an API call."""
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={"alicegh": ["alice"]}
    )

    result = workspace_client.resolve_github_usernames(["AliceGH"])

    assert result == {"AliceGH": "alice"}
    mock_api.get_github_usernames.assert_not_called()


def test_resolve_github_usernames_caches_map_with_ttl(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
    ldap_settings: Settings,
) -> None:
    """Test resolve_github_usernames caches the full map with the configured TTL."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {"alicegh": ["alice"]}

    workspace_client.resolve_github_usernames(["AliceGH"])

    mock_cache.set_obj.assert_called_once()
    call_args = mock_cache.set_obj.call_args
    assert call_args[1]["ttl"] == ldap_settings.ldap.github_usernames_cache_ttl


def test_resolve_github_usernames_double_check_locking(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames uses double-check locking on cache miss."""
    cached = CachedGithubUsernames(mapping={"alicegh": ["alice"]})
    mock_cache.get_obj.side_effect = [None, cached]

    result = workspace_client.resolve_github_usernames(["AliceGH"])

    assert result == {"AliceGH": "alice"}
    mock_api.get_github_usernames.assert_not_called()
    mock_cache.lock.assert_called_once()


def test_resolve_github_usernames_skips_and_logs_ambiguous_requested(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """A requested login mapping to >1 uid is skipped and logged once.

    LDAP result order must not decide identity, so an ambiguous requested login
    is omitted from the result. The warning names the requested login and all
    candidate uids so it is actionable.
    """
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={"shared-gh": ["alice", "mallory"], "bob-gh": ["bob"]}
    )

    with patch(
        "qontract_api.external.ldap.ldap_workspace_client.logger"
    ) as mock_logger:
        result = workspace_client.resolve_github_usernames(["Shared-GH", "bob-gh"])

    # Ambiguous login dropped; unambiguous one resolved.
    assert result == {"bob-gh": "bob"}
    mock_logger.warning.assert_called_once()
    _, kwargs = mock_logger.warning.call_args
    assert kwargs["github_login"] == "Shared-GH"
    assert kwargs["uids"] == ["alice", "mallory"]


def test_resolve_github_usernames_no_log_for_non_requested_ambiguous(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Ambiguity outside the requested logins produces no warning.

    The directory holds many ambiguous logins (orgs/repos claimed by several
    associates) that are irrelevant to the org being reconciled. Only requested
    logins are considered, so those never spam the logs.
    """
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={
            "stackrox": ["chsheth", "jvmartin"],  # ambiguous, but not requested
            "alicegh": ["alice"],
        }
    )

    with patch(
        "qontract_api.external.ldap.ldap_workspace_client.logger"
    ) as mock_logger:
        result = workspace_client.resolve_github_usernames(["AliceGH"])

    assert result == {"AliceGH": "alice"}
    mock_logger.warning.assert_not_called()
