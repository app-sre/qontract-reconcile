"""Tests for qontract_utils.gitlab_api module."""

# ruff: file-ignore[unused-function-argument]
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.gitlab_api import GitlabApi, GitlabApiCallContext
from qontract_utils.hooks import Hooks

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
