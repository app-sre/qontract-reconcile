"""Unit tests for GitlabWorkspaceClient."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.gitlab_api import GitlabGroup, GitlabProject

from qontract_api.gitlab.gitlab_workspace_client import (
    DEFAULT_BRANCH,
    README_COMMIT_MESSAGE,
    README_CONTENT,
    README_PATH,
    SAAS_BUNDLE_BRANCHES,
    CachedGroup,
    GitlabWorkspaceClient,
)

if TYPE_CHECKING:
    from qontract_api.config import Settings

URL = "https://gitlab.example.com"
TOKEN = "test-token"


@pytest.fixture
def mock_gitlab_repo_api_cls() -> Generator[MagicMock]:
    with patch("qontract_api.gitlab.gitlab_workspace_client.GitLabRepoApi") as mock_cls:
        yield mock_cls


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
        token=TOKEN,
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
        token=TOKEN,
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


def test_initiate_saas_bundle_repo_builds_project_scoped_vcs_client(
    client: GitlabWorkspaceClient,
    mock_gitlab_repo_api_cls: MagicMock,
    mock_settings: Settings,
) -> None:
    client.initiate_saas_bundle_repo(42)

    mock_gitlab_repo_api_cls.assert_called_once_with(
        project_id="42",
        token=TOKEN,
        gitlab_url=URL,
        timeout=mock_settings.gitlab_projects.api_timeout,
    )


def test_initiate_saas_bundle_repo_creates_readme_then_branches(
    client: GitlabWorkspaceClient,
    mock_gitlab_repo_api_cls: MagicMock,
) -> None:
    mock_vcs_client = mock_gitlab_repo_api_cls.return_value

    client.initiate_saas_bundle_repo(42)

    mock_vcs_client.create_file.assert_called_once_with(
        path=README_PATH,
        branch=DEFAULT_BRANCH,
        commit_message=README_COMMIT_MESSAGE,
        content=README_CONTENT,
    )
    branch_calls = [c.kwargs for c in mock_vcs_client.create_branch.call_args_list]
    assert branch_calls == [
        {"new_branch": branch, "source_branch": DEFAULT_BRANCH}
        for branch in SAAS_BUNDLE_BRANCHES
    ]


def test_initiate_saas_bundle_repo_does_not_touch_group_cache(
    client: GitlabWorkspaceClient,
    mock_gitlab_repo_api_cls: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Group membership is unaffected by bootstrapping a repo's content."""
    client.initiate_saas_bundle_repo(42)

    mock_cache.lock.assert_not_called()
    mock_cache.delete.assert_not_called()


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
        token=TOKEN,
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
