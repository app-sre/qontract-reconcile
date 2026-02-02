"""Tests for GitLab Repository API client with hooks."""

# ruff: noqa: ARG001
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.vcs.providers.gitlab_client import (
    GitLabApiCallContext,
    GitLabRepoApi,
)


@pytest.fixture
def mock_gitlab_client() -> Generator[MagicMock, None, None]:
    """Mock GitLab client."""
    with patch(
        "qontract_utils.vcs.providers.gitlab_client.gitlab.Gitlab"
    ) as mock_client:
        yield mock_client


@pytest.fixture
def gitlab_api(mock_gitlab_client: MagicMock) -> GitLabRepoApi:
    """Create GitLabRepoApi instance with mocked client."""
    return GitLabRepoApi(
        project_id="test-group/test-project",
        token="test-token",
        gitlab_url="https://gitlab.com",
    )


def test_gitlab_api_pre_hooks_includes_metrics_and_latency(
    mock_gitlab_client: MagicMock,
) -> None:
    """Test that metrics and latency hooks are always included."""
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
    )

    # Should have metrics, latency_start, and request_log hooks
    assert len(api._pre_hooks) >= 3


def test_gitlab_api_pre_hooks_custom(mock_gitlab_client: MagicMock) -> None:
    """Test custom pre_hooks are added after built-in hooks."""
    custom_hook = MagicMock()
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
        pre_hooks=[custom_hook],
    )

    # Should have built-in hooks + custom hook
    assert len(api._pre_hooks) == 4
    assert api._pre_hooks[-1] == custom_hook


def test_gitlab_api_post_hooks_includes_latency(
    mock_gitlab_client: MagicMock,
) -> None:
    """Test that latency_end hook is always included in post_hooks."""
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
    )

    # Should have at least the latency_end hook
    assert len(api._post_hooks) >= 1


def test_gitlab_api_post_hooks_custom(mock_gitlab_client: MagicMock) -> None:
    """Test custom post_hooks are added after latency hook."""
    custom_hook = MagicMock()
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
        post_hooks=[custom_hook],
    )

    # Should have latency_end hook + custom hook
    assert len(api._post_hooks) == 2
    assert api._post_hooks[-1] == custom_hook


def test_gitlab_api_error_hooks_custom(mock_gitlab_client: MagicMock) -> None:
    """Test custom error_hooks are added."""
    custom_hook = MagicMock()
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
        error_hooks=[custom_hook],
    )

    # Should have custom error hook
    assert len(api._error_hooks) == 1
    assert api._error_hooks[0] == custom_hook


def test_gitlab_api_get_file_calls_pre_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file calls pre_hooks before API call."""
    pre_hook = MagicMock()
    gitlab_api._pre_hooks = [pre_hook]

    # Mock project files.get
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(gitlab_api._project.files, "get", return_value=mock_file):
        gitlab_api.get_file("test.txt")

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert context.method == "get_file"
    assert context.repo_url == "https://gitlab.com/test-group/test-project"


def test_gitlab_api_get_file_calls_post_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file calls post_hooks after API call."""
    post_hook = MagicMock()
    gitlab_api._post_hooks = [post_hook]

    # Mock project files.get
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(gitlab_api._project.files, "get", return_value=mock_file):
        gitlab_api.get_file("test.txt")

    post_hook.assert_called_once()
    context = post_hook.call_args[0][0]
    assert context.method == "get_file"
    assert context.repo_url == "https://gitlab.com/test-group/test-project"


def test_gitlab_api_get_file_returns_content(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file returns file content."""
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(
        gitlab_api._project.files, "get", return_value=mock_file
    ) as mock_get:
        result = gitlab_api.get_file("test.txt")

    assert result == "file content"
    mock_get.assert_called_once_with(file_path="test.txt", ref="master")


def test_gitlab_api_get_file_with_custom_ref(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file with custom ref parameter."""
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(
        gitlab_api._project.files, "get", return_value=mock_file
    ) as mock_get:
        result = gitlab_api.get_file("test.txt", ref="develop")

    assert result == "file content"
    mock_get.assert_called_once_with(file_path="test.txt", ref="develop")


def test_gitlab_api_get_file_returns_none_on_exception(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file returns None when file not found."""
    with patch.object(
        gitlab_api._project.files, "get", side_effect=Exception("Not found")
    ):
        result = gitlab_api.get_file("nonexistent.txt")

    assert result is None


def test_gitlab_api_call_context_immutable() -> None:
    """Test GitLabApiCallContext is immutable (frozen dataclass)."""
    context = GitLabApiCallContext(
        method="get_file",
        repo_url="https://gitlab.com/group/project",
    )

    with pytest.raises(AttributeError):
        context.method = "different"  # type: ignore[misc]
