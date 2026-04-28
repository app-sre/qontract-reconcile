"""Tests for VCSWorkspaceClient caching layer."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.vcs.models import RepoOwners
from qontract_utils.vcs.provider_protocol import (
    CreateMergeRequestInput,
    FileAction,
    MergeRequestFile,
)

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings, VCSSettings
from qontract_api.external.vcs.provider_factory import VCSProviderFactory
from qontract_api.external.vcs.vcs_workspace_client import VCSWorkspaceClient


@pytest.fixture
def mock_provider_factory() -> MagicMock:
    """Create mock VCSProviderFactory."""
    factory = MagicMock(spec=VCSProviderFactory)
    mock_api_client = MagicMock()
    factory.create_api_client.return_value = (mock_api_client, "github")
    return factory


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
        vcs=VCSSettings(
            owners_cache_ttl=600,
        )
    )


@pytest.fixture
def github_client(
    mock_provider_factory: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> VCSWorkspaceClient:
    """Create VCSWorkspaceClient for GitHub with mocked dependencies."""
    return VCSWorkspaceClient(
        repo_url="https://github.com/test-org/test-repo",
        provider_factory=mock_provider_factory,
        cache=mock_cache,
        settings=settings,
    )


@pytest.fixture
def gitlab_client(
    mock_provider_factory: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> VCSWorkspaceClient:
    """Create VCSWorkspaceClient for GitLab with mocked dependencies."""
    # Override provider for GitLab
    mock_api_client = MagicMock()
    mock_provider_factory.create_api_client.return_value = (mock_api_client, "gitlab")

    return VCSWorkspaceClient(
        repo_url="https://gitlab.com/test-group/test-repo",
        provider_factory=mock_provider_factory,
        cache=mock_cache,
        settings=settings,
    )


def test_github_client_initialization(
    github_client: VCSWorkspaceClient,
    mock_provider_factory: MagicMock,
) -> None:
    """Test GitHub client initialization."""
    assert github_client.repo_url == "https://github.com/test-org/test-repo"
    assert github_client.provider_name == "github"
    mock_provider_factory.create_api_client.assert_called_once_with(
        "https://github.com/test-org/test-repo"
    )


def test_gitlab_client_initialization(gitlab_client: VCSWorkspaceClient) -> None:
    """Test GitLab client initialization."""
    assert gitlab_client.repo_url == "https://gitlab.com/test-group/test-repo"
    assert gitlab_client.provider_name == "gitlab"


def test_get_owners_cache_hit(
    github_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_owners returns cached data on cache hit."""
    # Setup cache hit
    cached_owners = RepoOwners(
        approvers=["user1", "user2"],
        reviewers=["user3"],
    )
    mock_cache.get_obj.return_value = cached_owners

    owners = github_client.get_owners(owners_file="/", ref="main")

    assert owners.approvers == ["user1", "user2"]
    assert owners.reviewers == ["user3"]
    mock_cache.get_obj.assert_called_once_with(
        "vcs:owners:https://github.com/test-org/test-repo:/:main",
        RepoOwners,
    )


def test_get_owners_cache_miss(
    github_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test get_owners fetches from API on cache miss."""
    # Mock the _fetch_owners method to avoid actual API calls
    github_client._fetch_owners = MagicMock(  # type: ignore[method-assign]
        return_value=RepoOwners(
            approvers=["api_user1"],
            reviewers=["api_user2"],
        )
    )

    owners = github_client.get_owners(owners_file="/", ref="main")

    assert owners.approvers == ["api_user1"]
    assert owners.reviewers == ["api_user2"]
    github_client._fetch_owners.assert_called_once_with("/", "main")
    mock_cache.set_obj.assert_called_once()
    # Verify TTL from settings
    call_args = mock_cache.set_obj.call_args
    # set_obj(key, value, ttl=...) - ttl is keyword arg
    assert call_args.kwargs["ttl"] == settings.vcs.owners_cache_ttl  # TTL = 600


def test_get_owners_acquires_lock_on_cache_miss(
    github_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_owners acquires distributed lock on cache miss."""
    # Mock _fetch_owners
    github_client._fetch_owners = MagicMock(  # type: ignore[method-assign]
        return_value=RepoOwners(approvers=[], reviewers=[])
    )

    github_client.get_owners(owners_file="/", ref="main")

    # Verify lock was acquired
    mock_cache.lock.assert_called_once_with(
        "vcs:owners:https://github.com/test-org/test-repo:/:main",
        timeout=30,
    )


def test_get_owners_double_check_after_lock(
    github_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_owners double-checks cache after acquiring lock."""
    # First call returns None (cache miss), second call returns cached data
    cached_owners = RepoOwners(
        approvers=["cached_user"],
        reviewers=[],
    )
    mock_cache.get_obj.side_effect = [None, cached_owners]  # Miss, then hit after lock

    owners = github_client.get_owners(owners_file="/", ref="main")

    # Should return cached data without calling _fetch_owners
    assert owners.approvers == ["cached_user"]
    assert owners.reviewers == []
    # Verify _fetch_owners was not called (no need to mock it)


def test_get_owners_different_paths(
    github_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_owners with different path values."""
    # Mock _fetch_owners
    github_client._fetch_owners = MagicMock(  # type: ignore[method-assign]
        return_value=RepoOwners(approvers=["user1"], reviewers=[])
    )

    # Test root path
    github_client.get_owners(owners_file="/", ref="main")
    assert (
        "vcs:owners:https://github.com/test-org/test-repo:/:main"
        in mock_cache.get_obj.call_args[0][0]
    )

    # Reset mock
    mock_cache.reset_mock()

    # Test subdirectory path
    github_client.get_owners(owners_file="/src/controllers", ref="main")
    assert (
        "vcs:owners:https://github.com/test-org/test-repo:/src/controllers:main"
        in mock_cache.get_obj.call_args[0][0]
    )


def test_get_owners_different_refs(
    github_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_owners with different ref values (branch, tag, SHA)."""
    # Mock _fetch_owners
    github_client._fetch_owners = MagicMock(  # type: ignore[method-assign]
        return_value=RepoOwners(approvers=["user1"], reviewers=[])
    )

    # Test branch ref
    github_client.get_owners(owners_file="/", ref="main")
    assert (
        "vcs:owners:https://github.com/test-org/test-repo:/:main"
        in mock_cache.get_obj.call_args[0][0]
    )

    # Reset mock
    mock_cache.reset_mock()

    # Test tag ref
    github_client.get_owners(owners_file="/", ref="v1.2.3")
    assert (
        "vcs:owners:https://github.com/test-org/test-repo:/:v1.2.3"
        in mock_cache.get_obj.call_args[0][0]
    )

    # Reset mock
    mock_cache.reset_mock()

    # Test commit SHA ref
    github_client.get_owners(owners_file="/", ref="abc123def456")
    assert (
        "vcs:owners:https://github.com/test-org/test-repo:/:abc123def456"
        in mock_cache.get_obj.call_args[0][0]
    )


def test_get_owners_empty_owners_file(
    github_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test get_owners handles empty OWNERS file."""
    # Mock _fetch_owners to return empty owners
    github_client._fetch_owners = MagicMock(  # type: ignore[method-assign]
        return_value=RepoOwners(approvers=[], reviewers=[])
    )

    owners = github_client.get_owners(owners_file="/", ref="main")

    assert owners.approvers == []
    assert owners.reviewers == []
    # Verify it was still cached
    mock_cache.set_obj.assert_called_once()


def test_gitlab_get_owners(
    gitlab_client: VCSWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Test GitLab client get_owners works identically to GitHub."""
    # Mock _fetch_owners
    gitlab_client._fetch_owners = MagicMock(  # type: ignore[method-assign]
        return_value=RepoOwners(
            approvers=["gitlab_user1"],
            reviewers=["gitlab_user2"],
        )
    )

    owners = gitlab_client.get_owners(owners_file="/", ref="main")

    assert owners.approvers == ["gitlab_user1"]
    assert owners.reviewers == ["gitlab_user2"]
    # get_obj is called twice: once before lock, once after (double-check pattern)
    assert mock_cache.get_obj.call_count == 2
    mock_cache.get_obj.assert_called_with(
        "vcs:owners:https://gitlab.com/test-group/test-repo:/:main",
        RepoOwners,
    )


def test_find_merge_request_delegates_to_api_client(
    github_client: VCSWorkspaceClient,
    mock_provider_factory: MagicMock,
) -> None:
    """Test find_merge_request delegates to the underlying API client."""
    api_client = mock_provider_factory.create_api_client.return_value[0]
    api_client.find_merge_request.return_value = "https://gitlab.com/mr/42"

    result = github_client.find_merge_request("[ldap-users] delete user alice")

    assert result == "https://gitlab.com/mr/42"
    api_client.find_merge_request.assert_called_once_with(
        "[ldap-users] delete user alice"
    )


def test_find_merge_request_returns_none(
    github_client: VCSWorkspaceClient,
    mock_provider_factory: MagicMock,
) -> None:
    """Test find_merge_request returns None when no MR found."""
    api_client = mock_provider_factory.create_api_client.return_value[0]
    api_client.find_merge_request.return_value = None

    result = github_client.find_merge_request("nonexistent title")

    assert result is None


def test_create_merge_request_delegates_to_api_client(
    github_client: VCSWorkspaceClient,
    mock_provider_factory: MagicMock,
) -> None:
    """Test create_merge_request delegates to the underlying API client."""
    api_client = mock_provider_factory.create_api_client.return_value[0]
    api_client.create_merge_request.return_value = "https://gitlab.com/mr/99"

    mr_input = CreateMergeRequestInput(
        title="Delete user",
        description="Cleanup",
        file_operations=[
            MergeRequestFile(
                path="data/users/foo.yml",
                action=FileAction.DELETE,
                commit_message="delete foo",
            ),
        ],
    )

    result = github_client.create_merge_request(mr_input)

    assert result == "https://gitlab.com/mr/99"
    api_client.create_merge_request.assert_called_once_with(mr_input)


def test_get_file_delegates_to_api_client(
    github_client: VCSWorkspaceClient,
    mock_provider_factory: MagicMock,
) -> None:
    """Test get_file delegates to the underlying API client."""
    api_client = mock_provider_factory.create_api_client.return_value[0]
    api_client.get_file.return_value = "file content"

    result = github_client.get_file(path="data/users/alice.yml", ref="master")

    assert result == "file content"
    api_client.get_file.assert_called_once_with("data/users/alice.yml", ref="master")


def test_get_file_returns_none_when_not_found(
    github_client: VCSWorkspaceClient,
    mock_provider_factory: MagicMock,
) -> None:
    """Test get_file returns None when file not found."""
    api_client = mock_provider_factory.create_api_client.return_value[0]
    api_client.get_file.return_value = None

    result = github_client.get_file(path="nonexistent.yml", ref="master")

    assert result is None
