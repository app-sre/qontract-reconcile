"""Tests for PagerDutyWorkspaceClient caching layer."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.pagerduty_api import PagerDutyApi, PagerDutyUser

from qontract_api.cache.base import CacheBackend
from qontract_api.config import PagerDutySettings, Settings
from qontract_api.external.pagerduty.pagerduty_workspace_client import (
    CachedEscalationPolicyUsers,
    CachedScheduleUsers,
    PagerDutyWorkspaceClient,
)


@pytest.fixture
def mock_pagerduty_api() -> MagicMock:
    """Create mock PagerDutyApi."""
    api = MagicMock(spec=PagerDutyApi)
    api.instance_name = "test-instance"
    return api


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock CacheBackend."""
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        pagerduty=PagerDutySettings(
            schedule_cache_ttl=300,
            escalation_policy_cache_ttl=600,
        )
    )


@pytest.fixture
def client(
    mock_pagerduty_api: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> PagerDutyWorkspaceClient:
    """Create PagerDutyWorkspaceClient with mocked dependencies."""
    return PagerDutyWorkspaceClient(
        pagerduty_api=mock_pagerduty_api,
        cache=mock_cache,
        settings=settings,
    )


def test_cache_key_schedule_users(client: PagerDutyWorkspaceClient) -> None:
    """Test schedule users cache key format."""
    cache_key = client._cache_key_schedule_users("SCHED123")
    assert cache_key == "pagerduty:test-instance:schedule:SCHED123:users"


def test_cache_key_escalation_policy_users(client: PagerDutyWorkspaceClient) -> None:
    """Test escalation policy users cache key format."""
    cache_key = client._cache_key_escalation_policy_users("POL456")
    assert cache_key == "pagerduty:test-instance:escalation_policy:POL456:users"


def test_get_schedule_users_cache_hit(
    client: PagerDutyWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_schedule_users returns cached data on cache hit."""
    # Setup cache hit with CachedScheduleUsers
    user = PagerDutyUser(id="PUSER1", name="John Doe", email="jdoe@example.com")
    cached = CachedScheduleUsers(items=[user])
    mock_cache.get_obj.return_value = cached

    users = client.get_schedule_users("SCHED123")

    assert len(users) == 1
    assert users[0].org_username == "jdoe"
    mock_cache.get_obj.assert_called_once_with(
        "pagerduty:test-instance:schedule:SCHED123:users",
        CachedScheduleUsers,
    )


def test_get_schedule_users_cache_miss(
    client: PagerDutyWorkspaceClient,
    mock_pagerduty_api: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test get_schedule_users fetches from API on cache miss."""
    # Setup API response
    api_user = PagerDutyUser(id="PUSER2", name="Jane Smith", email="jsmith@example.com")
    mock_pagerduty_api.get_schedule_users.return_value = [api_user]

    users = client.get_schedule_users("SCHED123")

    assert len(users) == 1
    assert users[0].org_username == "jsmith"
    mock_pagerduty_api.get_schedule_users.assert_called_once_with("SCHED123")
    mock_cache.set_obj.assert_called_once()
    # Verify TTL from settings
    call_args = mock_cache.set_obj.call_args
    assert call_args[0][2] == settings.pagerduty.schedule_cache_ttl  # TTL = 300


def test_get_schedule_users_acquires_lock_on_cache_miss(
    client: PagerDutyWorkspaceClient,
    mock_pagerduty_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_schedule_users acquires distributed lock on cache miss."""
    # Setup cache miss
    mock_pagerduty_api.get_schedule_users.return_value = []

    client.get_schedule_users("SCHED123")

    # Verify lock was acquired
    mock_cache.lock.assert_called_once_with(
        "pagerduty:test-instance:schedule:SCHED123:users"
    )


def test_get_escalation_policy_users_cache_hit(
    client: PagerDutyWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_escalation_policy_users returns cached data on cache hit."""
    # Setup cache hit
    user = PagerDutyUser(id="PUSER3", name="Bob Wilson", email="bwilson@example.com")
    cached = CachedEscalationPolicyUsers(items=[user])
    mock_cache.get_obj.return_value = cached

    users = client.get_escalation_policy_users("POL456")

    assert len(users) == 1
    assert users[0].org_username == "bwilson"
    mock_cache.get_obj.assert_called_once_with(
        "pagerduty:test-instance:escalation_policy:POL456:users",
        CachedEscalationPolicyUsers,
    )


def test_get_escalation_policy_users_cache_miss(
    client: PagerDutyWorkspaceClient,
    mock_pagerduty_api: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test get_escalation_policy_users fetches from API on cache miss."""
    # Setup cache miss

    # Setup API response
    api_user = PagerDutyUser(
        id="PUSER4", name="Alice Johnson", email="ajohnson@example.com"
    )
    mock_pagerduty_api.get_escalation_policy_users.return_value = [api_user]

    users = client.get_escalation_policy_users("POL456")

    assert len(users) == 1
    assert users[0].org_username == "ajohnson"
    mock_pagerduty_api.get_escalation_policy_users.assert_called_once_with("POL456")
    mock_cache.set_obj.assert_called_once()
    # Verify TTL from settings
    call_args = mock_cache.set_obj.call_args
    assert (
        call_args[0][2] == settings.pagerduty.escalation_policy_cache_ttl
    )  # TTL = 600


def test_get_escalation_policy_users_acquires_lock_on_cache_miss(
    client: PagerDutyWorkspaceClient,
    mock_pagerduty_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_escalation_policy_users acquires distributed lock on cache miss."""
    # Setup cache miss
    mock_pagerduty_api.get_escalation_policy_users.return_value = []

    client.get_escalation_policy_users("POL456")

    # Verify lock was acquired
    mock_cache.lock.assert_called_once_with(
        "pagerduty:test-instance:escalation_policy:POL456:users"
    )


def test_get_schedule_users_double_check_after_lock(
    client: PagerDutyWorkspaceClient,
    mock_pagerduty_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_schedule_users double-checks cache after acquiring lock."""
    # First call returns None (cache miss), second call returns cached data
    user = PagerDutyUser(id="PUSER5", name="Cached User", email="cached@example.com")
    cached = CachedScheduleUsers(items=[user])
    mock_cache.get_obj.side_effect = [None, cached]  # Miss, then hit after lock

    users = client.get_schedule_users("SCHED123")

    # Should return cached data without calling API
    assert len(users) == 1
    assert users[0].org_username == "cached"
    mock_pagerduty_api.get_schedule_users.assert_not_called()
    mock_cache.set_obj.assert_not_called()


def test_get_escalation_policy_users_double_check_after_lock(
    client: PagerDutyWorkspaceClient,
    mock_pagerduty_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_escalation_policy_users double-checks cache after acquiring lock."""
    # First call returns None (cache miss), second call returns cached data
    user = PagerDutyUser(id="PUSER6", name="Cached User", email="cached@example.com")
    cached = CachedEscalationPolicyUsers(items=[user])
    mock_cache.get_obj.side_effect = [None, cached]  # Miss, then hit after lock

    users = client.get_escalation_policy_users("POL456")

    # Should return cached data without calling API
    assert len(users) == 1
    assert users[0].org_username == "cached"
    mock_pagerduty_api.get_escalation_policy_users.assert_not_called()
    mock_cache.set_obj.assert_not_called()
