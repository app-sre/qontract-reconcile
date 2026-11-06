"""Tests for qontract_utils.gitlab_api module."""

# ruff: file-ignore[unused-function-argument]
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import gitlab
import pytest
from qontract_utils.gitlab_api import (
    GitlabAccessLevel,
    GitlabApi,
    GitlabApiCallContext,
    GitlabUserNotFoundError,
)
from qontract_utils.hooks import Hooks

# ---------------------------------------------------------------------------
# GitlabAccessLevel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (GitlabAccessLevel.GUEST, 10),
        (GitlabAccessLevel.REPORTER, 20),
        (GitlabAccessLevel.DEVELOPER, 30),
        (GitlabAccessLevel.MAINTAINER, 40),
        (GitlabAccessLevel.OWNER, 50),
    ],
)
def test_gitlab_access_level_to_access_level(
    level: GitlabAccessLevel, expected: int
) -> None:
    assert level.to_access_level() == expected


def test_gitlab_access_level_parses_from_string() -> None:
    assert GitlabAccessLevel("developer") == GitlabAccessLevel.DEVELOPER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gitlab_client() -> Generator[MagicMock]:
    with patch("qontract_utils.gitlab_api.client.gitlab.Gitlab") as mock_cls:
        yield mock_cls.return_value


@pytest.fixture
def gitlab_api(mock_gitlab_client: MagicMock) -> GitlabApi:
    return GitlabApi(url="https://gitlab.example.com", token="test-token")


def _project_mock(
    *,
    project_id: int = 42,
    name: str = "proj",
    path: str = "team/proj",
    web_url: str = "url",
) -> MagicMock:
    project = MagicMock()
    project.id = project_id
    project.name = name
    project.path_with_namespace = path
    project.web_url = web_url
    return project


def _member_mock(
    *,
    member_id: int = 1,
    username: str = "jsmith",
    name: str = "Jane Smith",
    access_level: int = 30,
) -> MagicMock:
    member = MagicMock()
    member.id = member_id
    member.username = username
    member.name = name
    member.access_level = access_level
    return member


def _user_mock(
    *, user_id: int = 1, username: str = "jsmith", name: str = "Jane Smith"
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.name = name
    return user


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_gitlab_api_stores_url() -> None:
    with patch("qontract_utils.gitlab_api.client.gitlab.Gitlab"):
        api = GitlabApi(url="https://gitlab.example.com", token="tok")
    assert api.url == "https://gitlab.example.com"


def test_gitlab_api_constructs_gitlab_client_with_expected_kwargs() -> None:
    with patch("qontract_utils.gitlab_api.client.gitlab.Gitlab") as mock_cls:
        GitlabApi(
            url="https://gitlab.example.com", token="tok", ssl_verify=False, timeout=10
        )
    args, kwargs = mock_cls.call_args
    assert args == ("https://gitlab.example.com",)
    assert kwargs["private_token"] == "tok"
    assert kwargs["ssl_verify"] is False
    assert kwargs["timeout"] == 10


def test_gitlab_api_pre_hooks_includes_metrics_and_latency(
    mock_gitlab_client: MagicMock,
) -> None:
    api = GitlabApi(url="https://gitlab.example.com", token="tok")
    assert len(api._hooks.pre_hooks) >= 2


def test_gitlab_api_post_hooks_includes_latency(mock_gitlab_client: MagicMock) -> None:
    api = GitlabApi(url="https://gitlab.example.com", token="tok")
    assert len(api._hooks.post_hooks) >= 1


# ---------------------------------------------------------------------------
# get_group
# ---------------------------------------------------------------------------


def test_get_group_returns_group_with_project_names(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    group = MagicMock()
    group.id = 7
    group.full_path = "team/sub"
    p1, p2 = MagicMock(), MagicMock()
    p1.name = "foo"
    p2.name = "bar"
    group.projects.list.return_value = [p1, p2]
    mock_gitlab_client.groups.get.return_value = group

    result = gitlab_api.get_group("team/sub")

    assert result.id == 7
    assert result.full_path == "team/sub"
    assert result.project_names == ["foo", "bar"]
    mock_gitlab_client.groups.get.assert_called_once_with("team/sub")
    group.projects.list.assert_called_once_with(iterator=True)


def test_get_group_calls_hooks(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    pre_hook = MagicMock()
    gitlab_api._hooks = Hooks(pre_hooks=[pre_hook])
    group = MagicMock()
    group.id = 1
    group.full_path = "team"
    group.projects.list.return_value = []
    mock_gitlab_client.groups.get.return_value = group

    gitlab_api.get_group("team")

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert context.method == "get_group"
    assert context.url == "https://gitlab.example.com"


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


def test_create_project_creates_under_group_and_returns_project(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    mock_gitlab_client.projects.create.return_value = _project_mock(
        project_id=1,
        name="newproj",
        path="team/newproj",
        web_url="https://x/team/newproj",
    )

    result = gitlab_api.create_project(group_id=99, name="newproj")

    mock_gitlab_client.projects.create.assert_called_once_with(
        {"name": "newproj", "namespace_id": 99}
    )
    assert result.id == 1
    assert result.name == "newproj"
    assert result.path_with_namespace == "team/newproj"
    assert result.web_url == "https://x/team/newproj"


def test_create_project_raises_exception_from_gitlab_api(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    mock_gitlab_client.projects.create.side_effect = (
        gitlab.exceptions.GitlabCreateError("Failed to create project")
    )

    with pytest.raises(gitlab.exceptions.GitlabCreateError):
        gitlab_api.create_project(group_id=99, name="newproj")

    mock_gitlab_client.projects.create.assert_called_once_with(
        {"name": "newproj", "namespace_id": 99}
    )


# ---------------------------------------------------------------------------
# get_group_members
# ---------------------------------------------------------------------------


def test_get_group_members_returns_members_excluding_bots(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    group = MagicMock()
    regular = _member_mock(member_id=1, username="jsmith", access_level=30)
    bot = _member_mock(member_id=2, username="group_42_bot_a1b2c3", access_level=40)
    group.members.list.return_value = [regular, bot]
    mock_gitlab_client.groups.get.return_value = group

    result = gitlab_api.get_group_members("team/sub")

    assert len(result) == 1
    assert result[0].id == 1
    assert result[0].username == "jsmith"
    assert result[0].access_level == 30
    mock_gitlab_client.groups.get.assert_called_once_with("team/sub")
    group.members.list.assert_called_once_with(iterator=True)


def test_get_group_members_keeps_username_resembling_bot_pattern(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    """A real username should not be mistaken for a generated bot account.

    Only a numeric group ID qualifies, e.g. "group_sales_bot_admin" is a
    plausible real username, not a bot.
    """
    group = MagicMock()
    lookalike = _member_mock(
        member_id=1, username="group_sales_bot_admin", access_level=30
    )
    group.members.list.return_value = [lookalike]
    mock_gitlab_client.groups.get.return_value = group

    result = gitlab_api.get_group_members("team/sub")

    assert [m.username for m in result] == ["group_sales_bot_admin"]


def test_get_group_members_empty_group(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    group = MagicMock()
    group.members.list.return_value = []
    mock_gitlab_client.groups.get.return_value = group

    assert gitlab_api.get_group_members("team/sub") == []


# ---------------------------------------------------------------------------
# get_user_by_username
# ---------------------------------------------------------------------------


def test_get_user_by_username_returns_user(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    mock_gitlab_client.users.list.return_value = [
        _user_mock(user_id=7, username="jsmith", name="Jane Smith")
    ]

    result = gitlab_api.get_user_by_username("jsmith")

    assert result.id == 7
    assert result.username == "jsmith"
    assert result.name == "Jane Smith"
    mock_gitlab_client.users.list.assert_called_once_with(username="jsmith")


def test_get_user_by_username_raises_when_not_found(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    mock_gitlab_client.users.list.return_value = []

    with pytest.raises(GitlabUserNotFoundError, match="jsmith"):
        gitlab_api.get_user_by_username("jsmith")


# ---------------------------------------------------------------------------
# add_group_member
# ---------------------------------------------------------------------------


def test_add_group_member_creates_member(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    group = MagicMock()
    group.members.create.return_value = _member_mock(
        member_id=7, username="jsmith", access_level=30
    )
    mock_gitlab_client.groups.get.return_value = group

    result = gitlab_api.add_group_member(
        "team/sub", user_id=7, access_level=GitlabAccessLevel.DEVELOPER
    )

    group.members.create.assert_called_once_with(
        {
            "user_id": 7,
            "access_level": 30,
        }
    )
    assert result.id == 7
    assert result.access_level == 30


def test_add_group_member_falls_back_to_update_when_already_member(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    group = MagicMock()
    group.members.create.side_effect = gitlab.exceptions.GitlabCreateError(
        "Member already exists"
    )
    existing_member = _member_mock(member_id=7, username="jsmith", access_level=20)
    group.members.get.return_value = existing_member
    mock_gitlab_client.groups.get.return_value = group

    result = gitlab_api.add_group_member(
        "team/sub", user_id=7, access_level=GitlabAccessLevel.DEVELOPER
    )

    group.members.get.assert_called_once_with(7)
    assert existing_member.access_level == 30
    existing_member.save.assert_called_once()
    assert result.id == 7
    assert result.access_level == 30


# ---------------------------------------------------------------------------
# remove_group_member
# ---------------------------------------------------------------------------


def test_remove_group_member_deletes_member(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    group = MagicMock()
    mock_gitlab_client.groups.get.return_value = group

    gitlab_api.remove_group_member("team/sub", member_id=7)

    mock_gitlab_client.groups.get.assert_called_once_with("team/sub")
    group.members.delete.assert_called_once_with(7)


# ---------------------------------------------------------------------------
# update_group_member_access
# ---------------------------------------------------------------------------


def test_update_group_member_access_saves_new_level(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    group = MagicMock()
    member = _member_mock(member_id=7, username="jsmith", access_level=30)
    group.members.get.return_value = member
    mock_gitlab_client.groups.get.return_value = group

    result = gitlab_api.update_group_member_access(
        "team/sub", member_id=7, access_level=GitlabAccessLevel.MAINTAINER
    )

    assert member.access_level == 40
    member.save.assert_called_once()
    assert result.access_level == 40


# ---------------------------------------------------------------------------
# close / context manager
# ---------------------------------------------------------------------------


def test_close_closes_session(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    gitlab_api.close()
    mock_gitlab_client.session.close.assert_called_once()


def test_context_manager_closes_on_exit(
    gitlab_api: GitlabApi, mock_gitlab_client: MagicMock
) -> None:
    with gitlab_api as api:
        assert api is gitlab_api
    mock_gitlab_client.session.close.assert_called_once()


def test_call_context_immutable() -> None:
    context = GitlabApiCallContext(method="get_group", url="https://gitlab.example.com")
    with pytest.raises(AttributeError):
        context.method = "different"  # type: ignore[misc]
