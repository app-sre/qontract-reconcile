"""Unit tests for SlackWorkspaceClient."""

# ruff: noqa: SLF001
# ruff: noqa: PLR2004 - Magic values acceptable in tests for readability

from unittest.mock import MagicMock

import pytest
from qontract_utils.slack_api import (
    SlackApi,
    SlackChannel,
    SlackUser,
    SlackUsergroup,
    SlackUserProfile,
)

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups.slack_workspace_client import (
    CachedChannels,
    CachedUsergroups,
    CachedUsers,
    SlackUsergroupNotFoundError,
    SlackWorkspaceClient,
)


@pytest.fixture
def mock_slack_api() -> MagicMock:
    """Create mock SlackApi."""
    mock = MagicMock(spec=SlackApi)
    mock.workspace_name = "test-workspace"
    return mock


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock CacheBackend."""
    return MagicMock(spec=CacheBackend)


@pytest.fixture
def mock_settings() -> Settings:
    """Create Settings with test values."""
    settings = Settings()
    settings.slack.usergroup_cache_ttl = 300
    settings.slack.users_cache_ttl = 900
    settings.slack.channels_cache_ttl = 900
    return settings


@pytest.fixture
def client(
    mock_slack_api: MagicMock, mock_cache: MagicMock, mock_settings: Settings
) -> SlackWorkspaceClient:
    """Create SlackWorkspaceClient with mocks."""
    return SlackWorkspaceClient(
        slack_api=mock_slack_api,
        cache=mock_cache,
        settings=mock_settings,
    )


def test_cache_key_users(client: SlackWorkspaceClient) -> None:
    """Test cache key generation for users."""
    assert client._cache_key_users() == "slack:test-workspace:users"


def test_cache_key_usergroups(client: SlackWorkspaceClient) -> None:
    """Test cache key generation for usergroups."""
    assert client._cache_key_usergroups() == "slack:test-workspace:usergroups"


def test_cache_key_channels(client: SlackWorkspaceClient) -> None:
    """Test cache key generation for channels."""
    assert client._cache_key_channels() == "slack:test-workspace:channels"


def test_get_users_cache_hit(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_users returns cached data on cache hit."""
    # Setup cache hit with CachedDict
    user = SlackUser(
        id="U1",
        name="user1",
        deleted=False,
        profile=SlackUserProfile(),
    )
    cached_dict = CachedUsers(items=[user])
    mock_cache.get_obj.return_value = cached_dict

    users = client.get_users()

    assert len(users) == 1
    assert "U1" in users
    assert users["U1"].name == "user1"
    mock_cache.get_obj.assert_called_once()
    client.slack_api.users_list.assert_not_called()  # type: ignore[attr-defined]


def test_get_users_cache_miss(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_users fetches from API on cache miss."""
    # Setup cache miss
    mock_cache.get_obj.return_value = None
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    # Setup API response
    mock_user = SlackUser(
        id="U1",
        name="user1",
        deleted=False,
        profile=SlackUserProfile(),
    )
    mock_slack_api.users_list.return_value = [mock_user]

    users = client.get_users()

    assert len(users) == 1
    assert "U1" in users
    mock_slack_api.users_list.assert_called_once()
    mock_cache.set_obj.assert_called_once()


def test_get_users_acquires_lock_on_cache_miss(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_users acquires distributed lock when fetching from API."""
    mock_cache.get_obj.return_value = None
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    mock_user = SlackUser(id="U1", name="user1", profile=SlackUserProfile())
    mock_slack_api.users_list.return_value = [mock_user]

    client.get_users()

    mock_cache.lock.assert_called_once_with("slack:test-workspace:users")


def test_get_usergroups_cache_hit(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_usergroups returns cached data on cache hit."""
    # Setup cache hit with CachedUsergroups
    ug = SlackUsergroup(id="UG1", handle="team", name="Team")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    usergroups = client.get_usergroups()

    assert len(usergroups) == 1
    assert "UG1" in usergroups
    assert usergroups["UG1"].handle == "team"
    client.slack_api.usergroups_list.assert_not_called()  # type: ignore[attr-defined]


def test_get_channels_cache_miss(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_channels fetches from API on cache miss."""
    mock_cache.get_obj.return_value = None
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    mock_channel = SlackChannel(id="C1", name="general")
    mock_slack_api.conversations_list.return_value = [mock_channel]

    channels = client.get_channels()

    assert len(channels) == 1
    assert "C1" in channels
    mock_slack_api.conversations_list.assert_called_once()


def test_get_users_by_ids(client: SlackWorkspaceClient, mock_cache: MagicMock) -> None:
    """Test get_users_by_ids returns subset of users."""
    # Setup cache hit with CachedUsers
    u1 = SlackUser(id="U1", name="user1", profile=SlackUserProfile())
    u2 = SlackUser(id="U2", name="user2", profile=SlackUserProfile())
    cached_dict = CachedUsers(items=[u1, u2])
    mock_cache.get_obj.return_value = cached_dict

    users = client.get_users_by_ids(["U1"])

    assert len(users) == 1
    assert users[0].id == "U1"
    assert all(u.id != "U2" for u in users)


def test_get_usergroup_by_handle(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_usergroup_by_handle finds usergroup."""
    # Setup cache hit with CachedUsergroups
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    usergroup = client.get_usergroup_by_handle("oncall")

    assert usergroup is not None
    assert usergroup.id == "UG1"
    assert usergroup.handle == "oncall"


def test_get_usergroup_by_handle_not_found(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_usergroup_by_handle returns None if not found."""
    # Setup cache hit with CachedUsergroups
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    usergroup = client.get_usergroup_by_handle("notfound")

    assert usergroup is None


def test_get_usergroup_by_id(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_usergroup_by_id finds usergroup."""
    # Setup cache hit with CachedUsergroups
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    usergroup = client.get_usergroup_by_id("UG1")

    assert usergroup is not None
    assert usergroup.id == "UG1"


def test_update_usergroup_calls_api_and_updates_cache(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup calls API and updates cache.

    WorkspaceClient accepts handle and converts to ID internally.
    SlackApi only accepts IDs.
    """
    # Setup cache with existing usergroup (for handle lookup)
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    updated_ug = SlackUsergroup(
        id="UG1",
        handle="oncall",
        name="Updated Name",
        description="Updated desc",
    )
    mock_slack_api.usergroups_update.return_value = updated_ug
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    # WorkspaceClient takes handle, converts to ID
    result = client.update_usergroup(
        handle="oncall",
        name="Updated Name",
        description="Updated desc",
    )

    assert result.name == "Updated Name"
    # SlackApi receives ID (not handle) and channel_ids parameter
    mock_slack_api.usergroups_update.assert_called_once_with(
        usergroup_id="UG1",
        name="Updated Name",
        description="Updated desc",
        channel_ids=None,
    )
    # Verify cache update was attempted
    mock_cache.lock.assert_called_once_with("slack:test-workspace:usergroups")


def test_update_usergroup_users_calls_api_and_updates_cache(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup_users calls API and updates cache.

    WorkspaceClient accepts handle and converts to ID internally.
    SlackApi only accepts IDs.
    """
    # Setup cache with existing usergroup (for handle lookup)
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    updated_ug = SlackUsergroup(
        id="UG1",
        handle="oncall",
        users=["U1", "U2"],
    )
    mock_slack_api.usergroups_users_update.return_value = updated_ug
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    # WorkspaceClient takes handle, converts to ID
    result = client.update_usergroup_users(
        handle="oncall",
        users=["U1", "U2"],
    )

    assert len(result.users) == 2
    # SlackApi receives ID (not handle) and user_ids parameter
    mock_slack_api.usergroups_users_update.assert_called_once_with(
        usergroup_id="UG1",
        user_ids=["U1", "U2"],
    )
    mock_cache.lock.assert_called_once()


def test_get_channels_by_ids(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_channels_by_ids returns subset of channels."""
    # Setup cache hit with CachedChannels
    c1 = SlackChannel(id="C1", name="general")
    c2 = SlackChannel(id="C2", name="random")
    cached_dict = CachedChannels(items=[c1, c2])
    mock_cache.get_obj.return_value = cached_dict

    channels = client.get_channels_by_ids(["C1"])

    assert len(channels) == 1
    assert channels[0].id == "C1"
    assert all(ch.id != "C2" for ch in channels)


def test_update_usergroup_with_channels(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup with channels parameter converts channel names to IDs.

    WorkspaceClient accepts channel names and converts them to IDs internally.
    """
    # Setup usergroups cache (for handle lookup)
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    ug_cached = CachedUsergroups(items=[ug])

    # Setup channels cache (for name → ID conversion)
    c1 = SlackChannel(id="C1", name="general")
    c2 = SlackChannel(id="C2", name="random")
    ch_cached = CachedChannels(items=[c1, c2])

    # Mock cache to return different objects based on call
    def mock_get_obj(key: str, _cls: type) -> CachedUsergroups | CachedChannels | None:
        if "usergroups" in key:
            return ug_cached
        if "channels" in key:
            return ch_cached
        return None

    mock_cache.get_obj.side_effect = mock_get_obj

    updated_ug = SlackUsergroup(
        id="UG1",
        handle="oncall",
        name="Updated Name",
        channels=["C1", "C2"],
    )
    mock_slack_api.usergroups_update.return_value = updated_ug
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    # WorkspaceClient takes channel NAMES, converts to IDs
    result = client.update_usergroup(
        handle="oncall",
        name="Updated Name",
        channels=["general", "random"],
    )

    assert result.name == "Updated Name"
    # Verify SlackApi received channel IDs (not names)
    mock_slack_api.usergroups_update.assert_called_once_with(
        usergroup_id="UG1",
        name="Updated Name",
        description=None,
        channel_ids=["C1", "C2"],
    )


def test_create_usergroup_with_handle_only(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test create_usergroup with handle only."""
    # Setup cache with existing usergroups
    existing_ug = SlackUsergroup(id="UG0", handle="existing", name="Existing")
    cached_dict = CachedUsergroups(items=[existing_ug])
    mock_cache.get_obj.return_value = cached_dict

    created_ug = SlackUsergroup(id="UG1", handle="new-team", name="new-team")
    mock_slack_api.usergroups_create.return_value = created_ug
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    result = client.create_usergroup(handle="new-team")

    assert result.id == "UG1"
    assert result.handle == "new-team"
    mock_slack_api.usergroups_create.assert_called_once_with(
        handle="new-team", name=None
    )
    # Verify cache update was attempted
    mock_cache.lock.assert_called_once_with("slack:test-workspace:usergroups")
    mock_cache.set_obj.assert_called_once()


def test_create_usergroup_with_custom_name(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test create_usergroup with handle and custom name."""
    # Setup cache with existing usergroups
    existing_ug = SlackUsergroup(id="UG0", handle="existing", name="Existing")
    cached_dict = CachedUsergroups(items=[existing_ug])
    mock_cache.get_obj.return_value = cached_dict

    created_ug = SlackUsergroup(id="UG1", handle="new-team", name="Custom Display Name")
    mock_slack_api.usergroups_create.return_value = created_ug
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    result = client.create_usergroup(handle="new-team", name="Custom Display Name")

    assert result.name == "Custom Display Name"
    mock_slack_api.usergroups_create.assert_called_once_with(
        handle="new-team", name="Custom Display Name"
    )


def test_update_usergroup_raises_error_if_handle_not_found(
    client: SlackWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup raises SlackUsergroupNotFoundError if handle not found."""
    # Setup cache with different usergroup
    ug = SlackUsergroup(id="UG1", handle="other", name="Other")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    # Should raise error when handle not found
    with pytest.raises(
        SlackUsergroupNotFoundError, match="Usergroup notfound not found"
    ):
        client.update_usergroup(
            handle="notfound",
            name="Updated Name",
        )


def test_update_usergroup_users_raises_error_if_handle_not_found(
    client: SlackWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup_users raises SlackUsergroupNotFoundError if handle not found."""
    # Setup cache with different usergroup
    ug = SlackUsergroup(id="UG1", handle="other", name="Other")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    # Should raise error when handle not found
    with pytest.raises(
        SlackUsergroupNotFoundError, match="Usergroup notfound not found"
    ):
        client.update_usergroup_users(
            handle="notfound",
            users=["U1", "U2"],
        )


def test_get_users_by_org_names(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_users_by_org_names filters by org_username and excludes deleted users."""
    # Setup cache with users
    u1 = SlackUser(
        id="U1",
        name="user1",
        deleted=False,
        profile=SlackUserProfile(email="user1@example.com"),
        org_username="user1",
    )
    u2 = SlackUser(
        id="U2",
        name="user2",
        deleted=False,
        profile=SlackUserProfile(email="user2@example.com"),
        org_username="user2",
    )
    u3 = SlackUser(
        id="U3",
        name="user3",
        deleted=True,
        profile=SlackUserProfile(email="user3@example.com"),
        org_username="user3",
    )
    cached_dict = CachedUsers(items=[u1, u2, u3])
    mock_cache.get_obj.return_value = cached_dict

    users = client.get_users_by_org_names(["user1", "user3"])

    # Should return user1 (active) but NOT user3 (deleted)
    assert len(users) == 1
    assert users[0].id == "U1"
    assert users[0].org_username == "user1"


def test_get_channels_by_names(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_channels_by_names returns channels matching names."""
    # Setup cache with channels
    c1 = SlackChannel(id="C1", name="general")
    c2 = SlackChannel(id="C2", name="random")
    c3 = SlackChannel(id="C3", name="dev")
    cached_dict = CachedChannels(items=[c1, c2, c3])
    mock_cache.get_obj.return_value = cached_dict

    channels = client.get_channels_by_names(["general", "dev"])

    assert len(channels) == 2
    assert {ch.name for ch in channels} == {"general", "dev"}
    assert {ch.id for ch in channels} == {"C1", "C3"}


def test_get_usergroups_cache_miss(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_usergroups fetches from API on cache miss."""
    mock_cache.get_obj.return_value = None
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    mock_ug = SlackUsergroup(id="UG1", handle="team", name="Team")
    mock_slack_api.usergroups_list.return_value = [mock_ug]

    usergroups = client.get_usergroups()

    assert len(usergroups) == 1
    assert "UG1" in usergroups
    mock_slack_api.usergroups_list.assert_called_once()
    mock_cache.set_obj.assert_called_once()
