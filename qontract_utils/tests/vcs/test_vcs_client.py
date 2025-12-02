"""Tests for VCS provider URL parsing and detection."""

import pytest
from qontract_utils.vcs.provider_registry import get_default_registry
from qontract_utils.vcs.providers.github_provider import GitHubProvider
from qontract_utils.vcs.providers.gitlab_provider import GitLabProvider


def test_github_provider_parse_url() -> None:
    """Test GitHub provider URL parsing."""
    provider = GitHubProvider()
    parsed = provider.parse_url("https://github.com/openshift/osdctl")
    assert parsed.owner == "openshift"
    assert parsed.name == "osdctl"


def test_github_provider_parse_url_with_git_suffix() -> None:
    """Test GitHub provider URL parsing with .git suffix."""
    provider = GitHubProvider()
    parsed = provider.parse_url("https://github.com/openshift/osdctl.git")
    assert parsed.owner == "openshift"
    assert parsed.name == "osdctl"


def test_github_provider_parse_url_with_trailing_slash() -> None:
    """Test GitHub provider URL parsing with trailing slash."""
    provider = GitHubProvider()
    parsed = provider.parse_url("https://github.com/openshift/osdctl/")
    assert parsed.owner == "openshift"
    assert parsed.name == "osdctl"


def test_gitlab_provider_parse_url() -> None:
    """Test GitLab provider URL parsing."""
    provider = GitLabProvider()
    parsed = provider.parse_url("https://gitlab.com/group/project")
    assert parsed.project_id == "group/project"
    assert parsed.gitlab_url == "https://gitlab.com"


def test_gitlab_provider_parse_url_with_git_suffix() -> None:
    """Test GitLab provider URL parsing with .git suffix."""
    provider = GitLabProvider()
    parsed = provider.parse_url("https://gitlab.com/group/project.git")
    assert parsed.project_id == "group/project"
    assert parsed.gitlab_url == "https://gitlab.com"


def test_gitlab_provider_parse_enterprise_url() -> None:
    """Test GitLab provider parsing enterprise URL."""
    provider = GitLabProvider()
    parsed = provider.parse_url("https://gitlab.example.com/mygroup/myrepo")
    assert parsed.project_id == "mygroup/myrepo"
    assert parsed.gitlab_url == "https://gitlab.example.com"


def test_github_provider_parse_enterprise_url() -> None:
    """Test GitHub provider parsing enterprise URL."""
    provider = GitHubProvider()
    parsed = provider.parse_url("https://github.example.com/myorg/myrepo")
    assert parsed.owner == "myorg"
    assert parsed.name == "myrepo"


def test_github_provider_detect() -> None:
    """Test GitHub provider URL detection."""
    provider = GitHubProvider()
    assert provider.detect("https://github.com/owner/repo") is True
    assert provider.detect("https://github.example.com/owner/repo") is True
    assert provider.detect("https://gitlab.com/owner/repo") is False


def test_gitlab_provider_detect() -> None:
    """Test GitLab provider URL detection."""
    provider = GitLabProvider()
    assert provider.detect("https://gitlab.com/owner/repo") is True
    assert provider.detect("https://gitlab.example.com/owner/repo") is True
    assert provider.detect("https://github.com/owner/repo") is False


def test_provider_registry_detect_github() -> None:
    """Test provider registry detects GitHub URLs."""
    registry = get_default_registry()
    provider = registry.detect_provider("https://github.com/openshift/osdctl")
    assert provider.name == "github"


def test_provider_registry_detect_gitlab() -> None:
    """Test provider registry detects GitLab URLs."""
    registry = get_default_registry()
    provider = registry.detect_provider("https://gitlab.com/group/project")
    assert provider.name == "gitlab"


def test_provider_registry_unsupported_provider() -> None:
    """Test provider registry raises error for unsupported VCS."""
    registry = get_default_registry()
    with pytest.raises(ValueError, match="No VCS provider found for URL"):
        registry.detect_provider("https://bitbucket.org/owner/repo")


def test_provider_registry_get_provider() -> None:
    """Test provider registry get provider by name."""
    registry = get_default_registry()
    github_provider = registry.get_provider("github")
    assert github_provider.name == "github"

    gitlab_provider = registry.get_provider("gitlab")
    assert gitlab_provider.name == "gitlab"


def test_provider_registry_get_unknown_provider() -> None:
    """Test provider registry raises error for unknown provider."""
    registry = get_default_registry()
    with pytest.raises(ValueError, match="Provider not found: bitbucket"):
        registry.get_provider("bitbucket")


def test_github_provider_parse_invalid_url_missing_repo() -> None:
    """Test GitHub provider parsing URL with missing repository name."""
    provider = GitHubProvider()
    with pytest.raises(ValueError, match="Invalid GitHub URL format"):
        provider.parse_url("https://github.com/openshift")


def test_github_provider_parse_invalid_url_empty_path() -> None:
    """Test GitHub provider parsing URL with empty path."""
    provider = GitHubProvider()
    with pytest.raises(ValueError, match="Invalid GitHub URL format"):
        provider.parse_url("https://github.com/")
