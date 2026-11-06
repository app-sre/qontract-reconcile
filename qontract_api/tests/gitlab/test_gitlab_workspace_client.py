"""Unit tests for GitlabWorkspaceClient."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.gitlab_api import (
    GitlabAccessLevel,
    GitlabGroup,
    GitlabGroupMember,
    GitlabProject,
    GitlabUser,
)

from qontract_api.gitlab.gitlab_workspace_client import (
    CachedGroup,
    CachedGroupMembers,
    GitlabWorkspaceClient,
)

if TYPE_CHECKING:
    from qontract_api.config import Settings

URL = "https://gitlab.example.com"


@pytest.fixture
def client(
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> GitlabWorkspaceClient:
    return GitlabWorkspaceClient(
        gitlab_api=mock_gitlab_api,
        url=URL,
        cache=mock_cache,
        settings=mock_settings,
    )


def _group(
    group_id: int = 1, full_path: str = "team", project_names: list[str] | None = None
) -> GitlabGroup:
    return GitlabGroup(
        id=group_id, full_path=full_path, project_names=project_names or []
    )


def _project(
    project_id: int = 1,
    name: str = "proj",
    path: str = "team/proj",
    web_url: str = "url",
) -> GitlabProject:
    return GitlabProject(
        id=project_id, name=name, path_with_namespace=path, web_url=web_url
    )


def _member(
    member_id: int = 1,
    username: str = "jsmith",
    name: str = "Jane Smith",
    access_level: int = 30,
) -> GitlabGroupMember:
    return GitlabGroupMember(
        id=member_id, username=username, name=name, access_level=access_level
    )


def _user(
    user_id: int = 1, username: str = "jsmith", name: str = "Jane Smith"
) -> GitlabUser:
    return GitlabUser(id=user_id, username=username, name=name)


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def test_cache_key_group(client: GitlabWorkspaceClient) -> None:
    assert (
        client._cache_key_group("team")
        == "gitlab:https://gitlab.example.com:group:team:projects"
    )


def test_cache_key_strips_trailing_slash(
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    c = GitlabWorkspaceClient(
        gitlab_api=mock_gitlab_api,
        url="https://gitlab.example.com/",
        cache=mock_cache,
        settings=mock_settings,
    )
    assert (
        c._cache_key_group("team")
        == "gitlab:https://gitlab.example.com:group:team:projects"
    )


# ---------------------------------------------------------------------------
# get_group — cache hit
# ---------------------------------------------------------------------------


def test_get_group_cache_hit(
    client: GitlabWorkspaceClient, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = CachedGroup(id=7, project_names=["foo"])

    group = client.get_group("team")

    assert group.id == 7
    assert group.full_path == "team"
    assert group.project_names == ["foo"]
    mock_cache.get_obj.assert_called_once()
    client.gitlab_api.get_group.assert_not_called()  # type: ignore[attr-defined]


def test_get_group_cache_hit_skips_lock(
    client: GitlabWorkspaceClient, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = CachedGroup(id=7, project_names=[])

    client.get_group("team")

    mock_cache.lock.assert_not_called()


# ---------------------------------------------------------------------------
# get_group — cache miss
# ---------------------------------------------------------------------------


def test_get_group_cache_miss_calls_api(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_gitlab_api.get_group.return_value = _group(project_names=["bar"])

    group = client.get_group("team")

    assert group.project_names == ["bar"]
    mock_gitlab_api.get_group.assert_called_once_with("team")


def test_get_group_cache_miss_stores_result(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_gitlab_api.get_group.return_value = _group(group_id=3, project_names=["bar"])

    client.get_group("team")

    mock_cache.set_obj.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:projects",
        CachedGroup(id=3, project_names=["bar"]),
        mock_settings.gitlab_projects.group_projects_cache_ttl,
    )


def test_get_group_cache_miss_acquires_lock(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_gitlab_api.get_group.return_value = _group()

    client.get_group("team")

    mock_cache.lock.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:projects"
    )


def test_get_group_double_check_inside_lock(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Second get_obj call (inside lock) returns data -> API must not be called."""
    cached = CachedGroup(id=9, project_names=["cached-inside-lock"])
    mock_cache.get_obj.side_effect = [None, cached]

    group = client.get_group("team")

    assert group.project_names == ["cached-inside-lock"]
    mock_gitlab_api.get_group.assert_not_called()
    mock_cache.set_obj.assert_not_called()


# ---------------------------------------------------------------------------
# get_group_members
# ---------------------------------------------------------------------------


def test_get_group_members_cache_hit(
    client: GitlabWorkspaceClient, mock_gitlab_api: MagicMock, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = CachedGroupMembers(members=[_member()])

    members = client.get_group_members("team")

    assert members == [_member()]
    mock_gitlab_api.get_group_members.assert_not_called()


def test_get_group_members_cache_miss_calls_api_and_stores(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_gitlab_api.get_group_members.return_value = [_member(member_id=7)]

    members = client.get_group_members("team")

    assert members == [_member(member_id=7)]
    mock_gitlab_api.get_group_members.assert_called_once_with("team")
    mock_cache.set_obj.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:members",
        CachedGroupMembers(members=[_member(member_id=7)]),
        mock_settings.gitlab_projects.group_members_cache_ttl,
    )


def test_get_group_members_double_check_inside_lock(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    cached = CachedGroupMembers(members=[_member(username="cached-inside-lock")])
    mock_cache.get_obj.side_effect = [None, cached]

    members = client.get_group_members("team")

    assert members[0].username == "cached-inside-lock"
    mock_gitlab_api.get_group_members.assert_not_called()


# ---------------------------------------------------------------------------
# get_user_by_username
# ---------------------------------------------------------------------------


def test_get_user_by_username_cache_hit(
    client: GitlabWorkspaceClient, mock_gitlab_api: MagicMock, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = _user(username="jsmith")

    user = client.get_user_by_username("jsmith")

    assert user.username == "jsmith"
    mock_gitlab_api.get_user_by_username.assert_not_called()


def test_get_user_by_username_cache_miss_calls_api_and_stores(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_gitlab_api.get_user_by_username.return_value = _user(
        user_id=7, username="jsmith"
    )

    user = client.get_user_by_username("jsmith")

    assert user.id == 7
    mock_gitlab_api.get_user_by_username.assert_called_once_with("jsmith")
    mock_cache.set_obj.assert_called_once_with(
        "gitlab:https://gitlab.example.com:user:jsmith",
        _user(user_id=7, username="jsmith"),
        mock_settings.gitlab_projects.group_members_cache_ttl,
    )


# ---------------------------------------------------------------------------
# Mutations — delegate + invalidate
# ---------------------------------------------------------------------------


def test_create_project_delegates_and_invalidates(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_gitlab_api.create_project.return_value = _project(name="newproj")

    project = client.create_project("team", group_id=1, name="newproj")

    assert project.name == "newproj"
    mock_gitlab_api.create_project.assert_called_once_with(1, "newproj")
    mock_cache.delete.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:projects"
    )


def test_create_project_acquires_lock_before_api_call(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    call_order: list[str] = []
    mock_cache.lock.return_value.__enter__ = MagicMock(
        side_effect=lambda *_: call_order.append("lock")
    )

    def _create_project(*_: object) -> GitlabProject:
        call_order.append("api")
        return _project()

    mock_gitlab_api.create_project.side_effect = _create_project

    client.create_project("team", group_id=1, name="newproj")

    assert call_order == ["lock", "api"]


def test_lock_failure_prevents_create_project(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.lock.return_value.__enter__.side_effect = RuntimeError(
        "lock unavailable"
    )

    with pytest.raises(RuntimeError, match="lock unavailable"):
        client.create_project("team", group_id=1, name="newproj")

    mock_gitlab_api.create_project.assert_not_called()
    mock_cache.delete.assert_not_called()


def test_add_group_member_delegates_and_invalidates(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_gitlab_api.add_group_member.return_value = _member(
        member_id=7, access_level=30
    )

    member = client.add_group_member(
        "team", user_id=7, access_level=GitlabAccessLevel.DEVELOPER
    )

    assert member.id == 7
    mock_gitlab_api.add_group_member.assert_called_once_with(
        "team", 7, GitlabAccessLevel.DEVELOPER
    )
    mock_cache.delete.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:members"
    )


def test_add_group_member_invalidates_even_on_error(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_gitlab_api.add_group_member.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        client.add_group_member(
            "team", user_id=7, access_level=GitlabAccessLevel.DEVELOPER
        )

    mock_cache.delete.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:members"
    )


def test_remove_group_member_delegates_and_invalidates(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.remove_group_member("team", member_id=7)

    mock_gitlab_api.remove_group_member.assert_called_once_with("team", 7)
    mock_cache.delete.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:members"
    )


def test_update_group_member_access_delegates_and_invalidates(
    client: GitlabWorkspaceClient,
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_gitlab_api.update_group_member_access.return_value = _member(
        member_id=7, access_level=40
    )

    member = client.update_group_member_access(
        "team", member_id=7, access_level=GitlabAccessLevel.MAINTAINER
    )

    assert member.access_level == 40
    mock_gitlab_api.update_group_member_access.assert_called_once_with(
        "team", 7, GitlabAccessLevel.MAINTAINER
    )
    mock_cache.delete.assert_called_once_with(
        "gitlab:https://gitlab.example.com:group:team:members"
    )


# ---------------------------------------------------------------------------
# Cache key isolation
# ---------------------------------------------------------------------------


def test_cache_key_isolated_by_group(client: GitlabWorkspaceClient) -> None:
    assert client._cache_key_group("team-a") != client._cache_key_group("team-b")


def test_cache_key_isolated_by_instance(
    mock_gitlab_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    c = GitlabWorkspaceClient(
        gitlab_api=mock_gitlab_api,
        url="https://gitlab.other.com",
        cache=mock_cache,
        settings=mock_settings,
    )
    assert (
        c._cache_key_group("team")
        == "gitlab:https://gitlab.other.com:group:team:projects"
    )


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_closes_gitlab_api(
    client: GitlabWorkspaceClient, mock_gitlab_api: MagicMock
) -> None:
    with client:
        pass

    mock_gitlab_api.close.assert_called_once()
