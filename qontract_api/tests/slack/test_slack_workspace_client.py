"""Unit tests for SlackWorkspaceClient.chat_post_message method."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from qontract_utils.slack_api import (
    ChatPostMessageResponse,
    SlackApiError,
    SlackChannel,
    SlackEnterpriseUser,
    SlackMessage,
    SlackUser,
    SlackUsergroup,
    SlackUsergroupPrefs,
    SlackUserProfile,
)

from qontract_api.slack.slack_workspace_client import (
    CachedChannels,
    CachedUsergroups,
    CachedUsers,
    SlackUsergroupNotFoundError,
    SlackWorkspaceClient,
)

if TYPE_CHECKING:
    from qontract_api.config import Settings


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
    mock_channel = SlackChannel(id="C1", name="general")
    mock_slack_api.conversations_list.return_value = [mock_channel]

    channels = client.get_channels()

    assert len(channels) == 1
    assert "C1" in channels
    mock_slack_api.conversations_list.assert_called_once()


def test_get_usergroup_by_handle(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test get_usergroup_by_handle finds usergroup."""
    # Setup cache hit with CachedUsergroups
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    usergroup = client._get_usergroup_by_handle("oncall")

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

    usergroup = client._get_usergroup_by_handle("notfound")

    assert usergroup is None


def test_update_usergroup_calls_api_and_clears_cache(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup calls API and clears cache.

    WorkspaceClient accepts handle and converts to ID internally.
    SlackApi only accepts IDs.
    """
    # Setup cache with existing usergroup (for handle lookup)
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_dict = CachedUsergroups(items=[ug])
    mock_cache.get_obj.return_value = cached_dict

    # WorkspaceClient takes handle, converts to ID
    client.update_usergroup(
        handle="oncall",
        description="Updated desc",
        channels=[],
    )

    # SlackApi receives ID (not handle) and channel_ids parameter
    mock_slack_api.usergroup_update.assert_called_once_with(
        usergroup_id="UG1",
        description="Updated desc",
        channel_ids=[],
    )
    # Verify cache was cleared
    mock_cache.delete.assert_called_once_with("slack:test-workspace:usergroups")


def test_update_usergroup_users_calls_api_and_clears_cache(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup_users calls API and clears cache.

    WorkspaceClient accepts handle and org usernames, converts to usergroup ID
    and Slack user IDs internally. SlackApi only accepts IDs.
    """
    # Setup cache with existing usergroup (for handle lookup)
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_usergroups = CachedUsergroups(items=[ug])

    # Setup cache with users (for org_username -> ID mapping)
    # NOTE: org_username is calculated from profile.email (email prefix before @)
    user1 = SlackUser(
        id="U1",
        name="John Smith",
        deleted=False,
        profile=SlackUserProfile(email="jsmith@example.com"),  # org_username = "jsmith"
    )
    user2 = SlackUser(
        id="U2",
        name="Mary Doe",
        deleted=False,
        profile=SlackUserProfile(email="mdoe@example.com"),  # org_username = "mdoe"
    )
    cached_users = CachedUsers(items=[user1, user2])

    # Mock get_obj: returns usergroups for usergroup cache key, users for user cache key
    def get_obj_side_effect(
        cache_key: str, *_args: Any, **_kwargs: Any
    ) -> CachedUsergroups | CachedUsers | None:
        if "usergroups" in cache_key:
            return cached_usergroups
        if "users" in cache_key:
            return cached_users
        return None

    mock_cache.get_obj.side_effect = get_obj_side_effect

    # WorkspaceClient takes handle and org usernames, converts to IDs
    client.update_usergroup_users(
        handle="oncall",
        users=["jsmith", "mdoe"],  # org usernames, not IDs!
    )

    # SlackApi receives usergroup ID and user IDs (mapped from org usernames)
    mock_slack_api.usergroup_users_update.assert_called_once_with(
        usergroup_id="UG1",
        user_ids=["U1", "U2"],
    )
    # Verify cache was cleared
    mock_cache.delete.assert_called_once_with("slack:test-workspace:usergroups")


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

    # WorkspaceClient takes channel NAMES, converts to IDs
    client.update_usergroup(
        handle="oncall",
        description="Updated desc",
        channels=["general", "random"],
    )

    # Verify SlackApi received channel IDs (not names)
    mock_slack_api.usergroup_update.assert_called_once_with(
        usergroup_id="UG1",
        description="Updated desc",
        channel_ids=["C1", "C2"],
    )
    # Verify cache was cleared
    mock_cache.delete.assert_called_once_with("slack:test-workspace:usergroups")


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
    mock_slack_api.usergroup_create.return_value = created_ug
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    result = client.create_usergroup(handle="new-team")

    assert result.id == "UG1"
    assert result.handle == "new-team"
    mock_slack_api.usergroup_create.assert_called_once_with(
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
    mock_slack_api.usergroup_create.return_value = created_ug
    mock_cache.lock.return_value.__enter__ = MagicMock()
    mock_cache.lock.return_value.__exit__ = MagicMock(return_value=False)

    result = client.create_usergroup(handle="new-team", name="Custom Display Name")

    assert result.name == "Custom Display Name"
    mock_slack_api.usergroup_create.assert_called_once_with(
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
            handle="notfound", description="Desc", channels=["general"]
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
            users=["jsmith", "mdoe"],  # org usernames
        )


def test_get_usergroups_cache_miss(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_usergroups fetches from API on cache miss."""
    mock_ug = SlackUsergroup(id="UG1", handle="team", name="Team")
    mock_slack_api.usergroups_list.return_value = [mock_ug]

    usergroups = client.get_usergroups()

    assert len(usergroups) == 1
    assert "UG1" in usergroups
    mock_slack_api.usergroups_list.assert_called_once()
    mock_cache.set_obj.assert_called_once()


def test_update_usergroup_users_with_empty_list_uses_deleted_user(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup_users with empty list uses a deleted user.

    When users list is empty, Slack API requires at least one user.
    The workaround is to use a deleted user to keep the handle alive.
    """
    # Setup cache with existing usergroup
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_usergroups = CachedUsergroups(items=[ug])

    # Setup cache with users (including one deleted user)
    user1 = SlackUser(
        id="U1",
        name="Active User",
        deleted=False,
        profile=SlackUserProfile(email="active@example.com"),
    )
    deleted_user = SlackUser(
        id="U_DELETED",
        name="Deleted User",
        deleted=True,
        profile=SlackUserProfile(email="deleted@example.com"),
    )
    cached_users = CachedUsers(items=[user1, deleted_user])

    # Mock get_obj
    def get_obj_side_effect(
        cache_key: str, *_args: Any, **_kwargs: Any
    ) -> CachedUsergroups | CachedUsers | None:
        if "usergroups" in cache_key:
            return cached_usergroups
        if "users" in cache_key:
            return cached_users
        return None

    mock_cache.get_obj.side_effect = get_obj_side_effect

    # Call with empty users list
    client.update_usergroup_users(
        handle="oncall",
        users=[],
    )

    # Verify deleted user was used
    mock_slack_api.usergroup_users_update.assert_called_once_with(
        usergroup_id="UG1",
        user_ids=["U_DELETED"],
    )
    # Verify cache was cleared
    mock_cache.delete.assert_called_once_with("slack:test-workspace:usergroups")


def test_update_usergroup_users_with_empty_list_no_deleted_users_raises_error(
    client: SlackWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup_users with empty list raises error when no deleted users exist."""
    # Setup cache with existing usergroup
    ug = SlackUsergroup(id="UG1", handle="oncall", name="On-Call")
    cached_usergroups = CachedUsergroups(items=[ug])

    # Setup cache with only active users (no deleted users)
    user1 = SlackUser(
        id="U1",
        name="Active User 1",
        deleted=False,
        profile=SlackUserProfile(email="user1@example.com"),
    )
    user2 = SlackUser(
        id="U2",
        name="Active User 2",
        deleted=False,
        profile=SlackUserProfile(email="user2@example.com"),
    )
    cached_users = CachedUsers(items=[user1, user2])

    # Mock get_obj
    def get_obj_side_effect(
        cache_key: str, *_args: Any, **_kwargs: Any
    ) -> CachedUsergroups | CachedUsers | None:
        if "usergroups" in cache_key:
            return cached_usergroups
        if "users" in cache_key:
            return cached_users
        return None

    mock_cache.get_obj.side_effect = get_obj_side_effect

    # Should raise error when no deleted users available
    with pytest.raises(
        RuntimeError, match="No deleted users found to assign to empty usergroup"
    ):
        client.update_usergroup_users(
            handle="oncall",
            users=[],
        )


def test_update_usergroup_users_with_empty_list_reactivates_disabled_usergroup(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test update_usergroup_users reactivates disabled usergroup when updating with empty list."""
    # Setup cache with existing DISABLED usergroup
    ug = SlackUsergroup(
        id="UG1",
        handle="oncall",
        name="On-Call",
        date_delete=1234567890,  # disabled usergroups have date_delete set
    )
    cached_usergroups = CachedUsergroups(items=[ug])

    # Setup cache with users (including deleted user)
    deleted_user = SlackUser(
        id="U_DELETED",
        name="Deleted User",
        deleted=True,
        profile=SlackUserProfile(email="deleted@example.com"),
    )
    cached_users = CachedUsers(items=[deleted_user])

    # Mock get_obj
    def get_obj_side_effect(
        cache_key: str, *_args: Any, **_kwargs: Any
    ) -> CachedUsergroups | CachedUsers | None:
        if "usergroups" in cache_key:
            return cached_usergroups
        if "users" in cache_key:
            return cached_users
        return None

    mock_cache.get_obj.side_effect = get_obj_side_effect

    # Call with empty users list
    client.update_usergroup_users(
        handle="oncall",
        users=[],
    )

    # Verify usergroup was enabled first
    mock_slack_api.usergroup_enable.assert_called_once_with(usergroup_id="UG1")
    # Then users updated
    mock_slack_api.usergroup_users_update.assert_called_once_with(
        usergroup_id="UG1",
        user_ids=["U_DELETED"],
    )
    # Verify cache was cleared
    mock_cache.delete.assert_called_once_with("slack:test-workspace:usergroups")


def test_chat_post_message_resolves_channel_name(
    client: SlackWorkspaceClient, mock_slack_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Verify chat_post_message resolves channel name to ID and delegates."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )
    mock_response = ChatPostMessageResponse(
        ts="1234567890.123456",
        channel="C123456",
    )
    mock_slack_api.chat_post_message.return_value = mock_response

    result = client.chat_post_message(
        channel="general",
        text="Hello, world!",
    )

    mock_slack_api.chat_post_message.assert_called_once_with(
        channel_id="C123456",
        text="Hello, world!",
        thread_ts=None,
        icon_emoji=None,
        icon_url=None,
        username=None,
    )
    assert result.ts == "1234567890.123456"
    assert result.channel == "C123456"


def test_chat_post_message_with_thread_ts(
    client: SlackWorkspaceClient, mock_slack_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Verify thread_ts is passed through."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )
    mock_response = ChatPostMessageResponse(
        ts="1234567890.123457",
        channel="C123456",
        thread_ts="1234567890.123456",
    )
    mock_slack_api.chat_post_message.return_value = mock_response

    result = client.chat_post_message(
        channel="general",
        text="Reply message",
        thread_ts="1234567890.123456",
    )

    mock_slack_api.chat_post_message.assert_called_once_with(
        channel_id="C123456",
        text="Reply message",
        thread_ts="1234567890.123456",
        icon_emoji=None,
        icon_url=None,
        username=None,
    )
    assert result.thread_ts == "1234567890.123456"


def test_chat_post_message_strips_hash_prefix(
    client: SlackWorkspaceClient, mock_slack_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Verify channel name with '#' prefix is resolved correctly."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )
    mock_response = ChatPostMessageResponse(
        ts="1234567890.123456",
        channel="C123456",
    )
    mock_slack_api.chat_post_message.return_value = mock_response

    client.chat_post_message(
        channel="#general",
        text="Hello!",
    )

    mock_slack_api.chat_post_message.assert_called_once_with(
        channel_id="C123456",
        text="Hello!",
        thread_ts=None,
        icon_emoji=None,
        icon_url=None,
        username=None,
    )


def test_chat_post_message_channel_not_found_raises_value_error(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Verify ValueError is raised when channel name is not found."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )

    with pytest.raises(ValueError, match="Channel 'nonexistent' not found"):
        client.chat_post_message(
            channel="nonexistent",
            text="This will fail",
        )


def test_chat_post_message_propagates_slack_api_error(
    client: SlackWorkspaceClient, mock_slack_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Verify SlackApiError from slack_api propagates (not caught)."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )
    mock_slack_api.chat_post_message.side_effect = SlackApiError(
        message="channel_not_found", response={"error": "channel_not_found"}
    )

    with pytest.raises(SlackApiError) as exc_info:
        client.chat_post_message(
            channel="general",
            text="This will fail",
        )

    assert exc_info.value.response["error"] == "channel_not_found"


def _mock_usergroups_and_users(
    mock_cache: MagicMock,
    *,
    usergroups: list[SlackUsergroup] | None = None,
    users: list[SlackUser] | None = None,
) -> None:
    """Mock get_obj to return usergroups/users based on the cache key."""
    cached_usergroups = CachedUsergroups(items=usergroups or [])
    cached_users = CachedUsers(items=users or [])

    def get_obj_side_effect(
        cache_key: str, *_args: Any, **_kwargs: Any
    ) -> CachedUsergroups | CachedUsers | None:
        if "usergroups" in cache_key:
            return cached_usergroups
        if "users" in cache_key:
            return cached_users
        return None

    mock_cache.get_obj.side_effect = get_obj_side_effect


def test_resolve_mentions_usergroup_handle(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """A "@handle" matching a usergroup becomes a subteam mention."""
    _mock_usergroups_and_users(
        mock_cache,
        usergroups=[SlackUsergroup(id="UG1", handle="oncall-team", name="On-Call")],
    )

    result = client._resolve_mentions("Heads up @oncall-team!")

    assert result == "Heads up <!subteam^UG1>!"


def test_resolve_mentions_user_org_username(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """A "@handle" matching a user's org_username becomes a user mention."""
    _mock_usergroups_and_users(
        mock_cache,
        users=[
            SlackUser(
                id="U1", name="Jane", profile=SlackUserProfile(email="jsmith@x.com")
            )
        ],
    )

    result = client._resolve_mentions("cc @jsmith please")

    assert result == "cc <@U1> please"


def test_resolve_mentions_usergroup_takes_priority_over_user(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """When a handle matches both a usergroup and a username, usergroup wins."""
    _mock_usergroups_and_users(
        mock_cache,
        usergroups=[SlackUsergroup(id="UG1", handle="shared", name="Shared")],
        users=[
            SlackUser(
                id="U1", name="Shared", profile=SlackUserProfile(email="shared@x.com")
            )
        ],
    )

    result = client._resolve_mentions("@shared")

    assert result == "<!subteam^UG1>"


def test_resolve_mentions_unresolvable_left_unchanged(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """A "@handle" matching neither a usergroup nor a user is left as plain text."""
    _mock_usergroups_and_users(mock_cache)

    result = client._resolve_mentions("no such @typo-handle here")

    assert result == "no such @typo-handle here"


def test_resolve_mentions_does_not_match_email_addresses(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """An embedded email address is not treated as a mention."""
    _mock_usergroups_and_users(
        mock_cache,
        users=[
            SlackUser(
                id="U1", name="Jane", profile=SlackUserProfile(email="jsmith@x.com")
            )
        ],
    )

    result = client._resolve_mentions("contact jsmith@x.com for help")

    assert result == "contact jsmith@x.com for help"


def test_resolve_mentions_punctuation_prefixed(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """A "@handle" preceded by punctuation (not a word character) is resolved."""
    _mock_usergroups_and_users(
        mock_cache,
        usergroups=[SlackUsergroup(id="UG1", handle="oncall-team", name="On-Call")],
    )

    assert client._resolve_mentions("(@oncall-team)") == "(<!subteam^UG1>)"
    assert client._resolve_mentions("alert:@oncall-team") == "alert:<!subteam^UG1>"


def test_resolve_mentions_multiple_in_one_message(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Multiple mentions in the same message are all resolved."""
    _mock_usergroups_and_users(
        mock_cache,
        usergroups=[SlackUsergroup(id="UG1", handle="oncall-team", name="On-Call")],
        users=[
            SlackUser(
                id="U1", name="Jane", profile=SlackUserProfile(email="jsmith@x.com")
            )
        ],
    )

    result = client._resolve_mentions("@oncall-team and @jsmith, please look")

    assert result == "<!subteam^UG1> and <@U1>, please look"


def test_chat_post_message_resolves_mentions_in_text(
    client: SlackWorkspaceClient, mock_slack_api: MagicMock, mock_cache: MagicMock
) -> None:
    """chat_post_message resolves @handle mentions before posting."""
    cached_channels = CachedChannels(items=[SlackChannel(id="C1", name="alerts")])
    cached_usergroups = CachedUsergroups(
        items=[SlackUsergroup(id="UG1", handle="oncall-team", name="On-Call")]
    )

    def get_obj_side_effect(
        cache_key: str, *_args: Any, **_kwargs: Any
    ) -> CachedChannels | CachedUsergroups | CachedUsers | None:
        if "channels" in cache_key:
            return cached_channels
        if "usergroups" in cache_key:
            return cached_usergroups
        if "users" in cache_key:
            return CachedUsers(items=[])
        return None

    mock_cache.get_obj.side_effect = get_obj_side_effect
    mock_slack_api.chat_post_message.return_value = ChatPostMessageResponse(
        ts="1234567890.123456", channel="C1"
    )

    client.chat_post_message(channel="alerts", text="Heads up @oncall-team!")

    mock_slack_api.chat_post_message.assert_called_once_with(
        channel_id="C1",
        text="Heads up <!subteam^UG1>!",
        thread_ts=None,
        icon_emoji=None,
        icon_url=None,
        username=None,
    )


def test_get_flat_conversation_history_resolves_channel_name(
    client: SlackWorkspaceClient, mock_slack_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Verify get_flat_conversation_history resolves channel name to ID and delegates."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )
    mock_messages = [SlackMessage(ts="1700000002.000000", text="hi")]
    mock_slack_api.conversations_history.return_value = mock_messages

    result = client.get_flat_conversation_history(
        channel="general",
        from_timestamp=1700000000,
        to_timestamp=1700000100,
    )

    mock_slack_api.conversations_history.assert_called_once_with(
        channel_id="C123456",
        oldest="1700000000",
        latest="1700000100",
    )
    assert result == mock_messages


def test_get_flat_conversation_history_without_to_timestamp(
    client: SlackWorkspaceClient, mock_slack_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Verify to_timestamp=None is forwarded as latest=None (no upper bound)."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )
    mock_slack_api.conversations_history.return_value = []

    client.get_flat_conversation_history(
        channel="general",
        from_timestamp=1700000000,
        to_timestamp=None,
    )

    mock_slack_api.conversations_history.assert_called_once_with(
        channel_id="C123456",
        oldest="1700000000",
        latest=None,
    )


def test_get_flat_conversation_history_channel_not_found_raises_value_error(
    client: SlackWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Verify ValueError is raised when channel name is not found."""
    mock_cache.get_obj.return_value = CachedChannels(
        items=[SlackChannel(id="C123456", name="general")]
    )

    with pytest.raises(ValueError, match="Channel 'nonexistent' not found"):
        client.get_flat_conversation_history(
            channel="nonexistent",
            from_timestamp=1700000000,
            to_timestamp=None,
        )


def test_get_slack_usergroups_enterprise_grid_user_resolved(
    client: SlackWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Enterprise Grid users must appear in current state.

    usergroups_list returns workspace U... IDs in ug.users, but user.id returns
    the enterprise W... ID when enterprise_user is set. Without a dual-keyed lookup,
    Enterprise Grid users are silently dropped from current state every reconcile cycle,
    causing an infinite loop where the same users appear in users_to_add on every run.
    """
    enterprise_user = SlackEnterpriseUser(id="W_ENTERPRISE")
    user = SlackUser(
        id="U_WORKSPACE",
        name="testuser",
        deleted=False,
        profile=SlackUserProfile(email="testuser@example.com"),
        enterprise_user=enterprise_user,
    )
    # usergroups_list returns workspace-level U... IDs
    ug = SlackUsergroup(
        id="UG1",
        handle="oncall",
        users=["U_WORKSPACE"],
        prefs=SlackUsergroupPrefs(channels=[]),
    )

    def get_obj_side_effect(cache_key: str, *_args: Any, **_kwargs: Any) -> Any:
        if "usergroups" in cache_key:
            return CachedUsergroups(items=[ug])
        if "users" in cache_key:
            return CachedUsers(items=[user])
        if "channels" in cache_key:
            return CachedChannels(items=[])
        return None

    mock_cache.get_obj.side_effect = get_obj_side_effect

    result = client.get_slack_usergroups(["oncall"])

    assert len(result) == 1
    assert result[0].config.users == ["testuser"]
