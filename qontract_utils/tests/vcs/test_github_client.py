"""Tests for GitHub Repository API client with hooks."""

# ruff: noqa: ARG001
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.hooks import Hooks
from qontract_utils.vcs.providers.github_client import (
    GitHubApiCallContext,
    GitHubRepoApi,
)


@pytest.fixture
def mock_github_client() -> Generator[MagicMock, None, None]:
    """Mock GitHub client."""
    with patch("qontract_utils.vcs.providers.github_client.Github") as mock_client:
        yield mock_client


@pytest.fixture
def github_api(mock_github_client: MagicMock) -> GitHubRepoApi:
    """Create GitHubRepoApi instance with mocked client."""
    return GitHubRepoApi(
        owner="test-owner",
        repo="test-repo",
        token="test-token",
    )


def test_github_api_pre_hooks_includes_metrics_and_latency(
    mock_github_client: MagicMock,
) -> None:
    """Test that metrics and latency hooks are always included."""
    api = GitHubRepoApi(
        owner="owner",
        repo="repo",
        token="token",
    )

    # Should have metrics, latency_start, and request_log hooks
    assert len(api._hooks.pre_hooks) >= 3


def test_github_api_pre_hooks_custom(mock_github_client: MagicMock) -> None:
    """Test custom pre_hooks are added after built-in hooks."""
    custom_hook = MagicMock()
    api = GitHubRepoApi(
        owner="owner",
        repo="repo",
        token="token",
        hooks=Hooks(pre_hooks=[custom_hook]),
    )

    # Should have built-in hooks + custom hook
    assert len(api._hooks.pre_hooks) == 4
    assert custom_hook in api._hooks.pre_hooks


def test_github_api_post_hooks_includes_latency(
    mock_github_client: MagicMock,
) -> None:
    """Test that latency_end hook is always included in post_hooks."""
    api = GitHubRepoApi(
        owner="owner",
        repo="repo",
        token="token",
    )

    # Should have at least the latency_end hook
    assert len(api._hooks.post_hooks) >= 1


def test_github_api_post_hooks_custom(mock_github_client: MagicMock) -> None:
    """Test custom post_hooks are added after latency hook."""
    custom_hook = MagicMock()
    api = GitHubRepoApi(
        owner="owner",
        repo="repo",
        token="token",
        hooks=Hooks(post_hooks=[custom_hook]),
    )

    # Should have latency_end hook + custom hook
    assert len(api._hooks.post_hooks) == 2
    assert custom_hook in api._hooks.post_hooks


def test_github_api_error_hooks_custom(mock_github_client: MagicMock) -> None:
    """Test custom error_hooks are added."""
    custom_hook = MagicMock()
    api = GitHubRepoApi(
        owner="owner",
        repo="repo",
        token="token",
        hooks=Hooks(error_hooks=[custom_hook]),
    )

    # Should have custom error hook
    assert len(api._hooks.error_hooks) == 1
    assert api._hooks.error_hooks[0] == custom_hook


def test_github_api_get_file_calls_pre_hooks(
    github_api: GitHubRepoApi,
    mock_github_client: MagicMock,
) -> None:
    """Test get_file calls pre_hooks before API call."""
    pre_hook = MagicMock()
    github_api._hooks = Hooks(pre_hooks=[pre_hook])

    # Mock repository get_contents
    mock_content = MagicMock()
    mock_content.decoded_content = b"file content"
    with patch.object(
        github_api._repository, "get_contents", return_value=mock_content
    ):
        github_api.get_file("test.txt")

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert context.method == "get_file"
    assert context.repo_url == "https://github.com/test-owner/test-repo"


def test_github_api_get_file_calls_post_hooks(
    github_api: GitHubRepoApi,
    mock_github_client: MagicMock,
) -> None:
    """Test get_file calls post_hooks after API call."""
    post_hook = MagicMock()
    github_api._hooks = Hooks(post_hooks=[post_hook])

    # Mock repository get_contents
    mock_content = MagicMock()
    mock_content.decoded_content = b"file content"
    with patch.object(
        github_api._repository, "get_contents", return_value=mock_content
    ):
        github_api.get_file("test.txt")

    post_hook.assert_called_once()
    context = post_hook.call_args[0][0]
    assert context.method == "get_file"
    assert context.repo_url == "https://github.com/test-owner/test-repo"


def test_github_api_get_file_returns_content(
    github_api: GitHubRepoApi,
    mock_github_client: MagicMock,
) -> None:
    """Test get_file returns file content."""
    mock_content = MagicMock()
    mock_content.decoded_content = b"file content"
    with patch.object(
        github_api._repository, "get_contents", return_value=mock_content
    ) as mock_get:
        result = github_api.get_file("test.txt")

    assert result == "file content"
    mock_get.assert_called_once_with("test.txt", ref="master")


def test_github_api_get_file_returns_none_for_directory(
    github_api: GitHubRepoApi,
    mock_github_client: MagicMock,
) -> None:
    """Test get_file returns None when path is a directory."""
    # Mock repository get_contents returning a list (directory)
    with patch.object(github_api._repository, "get_contents", return_value=[]):
        result = github_api.get_file("directory")

    assert result is None


def test_github_api_get_file_returns_none_on_exception(
    github_api: GitHubRepoApi,
    mock_github_client: MagicMock,
) -> None:
    """Test get_file returns None when file not found."""
    with patch.object(
        github_api._repository, "get_contents", side_effect=Exception("Not found")
    ):
        result = github_api.get_file("nonexistent.txt")

    assert result is None


def test_github_api_call_context_immutable() -> None:
    """Test GitHubApiCallContext is immutable (frozen dataclass)."""
    context = GitHubApiCallContext(
        method="get_file",
        repo_url="https://github.com/owner/repo",
    )

    with pytest.raises(AttributeError):
        context.method = "different"  # type: ignore[misc]
