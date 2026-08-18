"""Unit tests for QuayWorkspaceClient."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.quay_api import QuayRepo

from qontract_api.quay.quay_workspace_client import CachedRepos, QuayWorkspaceClient

if TYPE_CHECKING:
    from qontract_api.config import Settings

BASE_URL = "https://quay.io"


@pytest.fixture
def client(
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> QuayWorkspaceClient:
    return QuayWorkspaceClient(
        quay_api=mock_quay_api,
        base_url=BASE_URL,
        cache=mock_cache,
        settings=mock_settings,
    )


def _repo(name: str, *, is_public: bool = True, description: str = "") -> QuayRepo:
    return QuayRepo(name=name, is_public=is_public, description=description)


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def test_cache_key_repos(client: QuayWorkspaceClient) -> None:
    assert client._cache_key_repos() == "quay:https://quay.io:myorg:repos"


def test_cache_key_strips_trailing_slash(
    mock_quay_api: MagicMock, mock_cache: MagicMock, mock_settings: Settings
) -> None:
    c = QuayWorkspaceClient(
        quay_api=mock_quay_api,
        base_url="https://quay.io/",
        cache=mock_cache,
        settings=mock_settings,
    )
    assert c._cache_key_repos() == "quay:https://quay.io:myorg:repos"


# ---------------------------------------------------------------------------
# get_repos — cache hit
# ---------------------------------------------------------------------------


def test_get_repos_cache_hit(
    client: QuayWorkspaceClient, mock_cache: MagicMock
) -> None:
    cached = CachedRepos(items=[_repo("foo")])
    mock_cache.get_obj.return_value = cached

    repos = client.get_repos()

    assert len(repos) == 1
    assert repos[0].name == "foo"
    mock_cache.get_obj.assert_called_once()
    client.quay_api.list_images.assert_not_called()  # type: ignore[attr-defined]


def test_get_repos_cache_hit_skips_lock(
    client: QuayWorkspaceClient, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = CachedRepos(items=[_repo("foo")])

    client.get_repos()

    mock_cache.lock.assert_not_called()


# ---------------------------------------------------------------------------
# get_repos — cache miss
# ---------------------------------------------------------------------------


def test_get_repos_cache_miss_calls_api(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_quay_api.list_images.return_value = [_repo("bar")]

    repos = client.get_repos()

    assert len(repos) == 1
    assert repos[0].name == "bar"
    mock_quay_api.list_images.assert_called_once()


def test_get_repos_cache_miss_stores_result(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_quay_api.list_images.return_value = [_repo("bar")]

    client.get_repos()

    mock_cache.set_obj.assert_called_once_with(
        "quay:https://quay.io:myorg:repos",
        CachedRepos(items=[_repo("bar")]),
        mock_settings.quay.repos_cache_ttl,
    )


def test_get_repos_cache_miss_acquires_lock(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.return_value = None
    mock_quay_api.list_images.return_value = []

    client.get_repos()

    mock_cache.lock.assert_called_once_with("quay:https://quay.io:myorg:repos")


def test_get_repos_double_check_inside_lock(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Second get_obj call (inside lock) returns data → API must not be called."""
    cached = CachedRepos(items=[_repo("cached-inside-lock")])
    mock_cache.get_obj.side_effect = [None, cached]

    repos = client.get_repos()

    assert repos[0].name == "cached-inside-lock"
    mock_quay_api.list_images.assert_not_called()
    mock_cache.set_obj.assert_not_called()


# ---------------------------------------------------------------------------
# Mutations — delegate + invalidate
# ---------------------------------------------------------------------------


def test_repo_create_delegates_and_invalidates(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.repo_create("new-repo", "A description", public=True)

    mock_quay_api.repo_create.assert_called_once_with(
        "new-repo", "A description", public=True
    )
    mock_cache.delete.assert_called_once_with("quay:https://quay.io:myorg:repos")


def test_repo_delete_delegates_and_invalidates(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.repo_delete("old-repo")

    mock_quay_api.repo_delete.assert_called_once_with("old-repo")
    mock_cache.delete.assert_called_once_with("quay:https://quay.io:myorg:repos")


def test_repo_update_description_delegates_and_invalidates(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.repo_update_description("myrepo", "new desc")

    mock_quay_api.repo_update_description.assert_called_once_with("myrepo", "new desc")
    mock_cache.delete.assert_called_once_with("quay:https://quay.io:myorg:repos")


def test_repo_make_public_delegates_and_invalidates(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.repo_make_public("myrepo")

    mock_quay_api.repo_make_public.assert_called_once_with("myrepo")
    mock_cache.delete.assert_called_once_with("quay:https://quay.io:myorg:repos")


def test_repo_make_private_delegates_and_invalidates(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.repo_make_private("myrepo")

    mock_quay_api.repo_make_private.assert_called_once_with("myrepo")
    mock_cache.delete.assert_called_once_with("quay:https://quay.io:myorg:repos")


def test_invalidate_acquires_lock(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.repo_delete("old-repo")

    mock_cache.lock.assert_called_once_with("quay:https://quay.io:myorg:repos")


def test_invalidate_lock_failure_is_swallowed(
    client: QuayWorkspaceClient,
    mock_quay_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.lock.side_effect = RuntimeError("lock unavailable")

    # Should not raise
    client.repo_delete("old-repo")

    mock_quay_api.repo_delete.assert_called_once()
    mock_cache.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Cache key isolation (different org/instance)
# ---------------------------------------------------------------------------


def test_cache_key_isolated_by_org(
    mock_quay_api: MagicMock, mock_cache: MagicMock, mock_settings: Settings
) -> None:
    mock_quay_api.org = "other-org"
    c = QuayWorkspaceClient(
        quay_api=mock_quay_api,
        base_url=BASE_URL,
        cache=mock_cache,
        settings=mock_settings,
    )
    assert c._cache_key_repos() == "quay:https://quay.io:other-org:repos"


def test_cache_key_isolated_by_instance(
    mock_quay_api: MagicMock, mock_cache: MagicMock, mock_settings: Settings
) -> None:
    c = QuayWorkspaceClient(
        quay_api=mock_quay_api,
        base_url="https://quay.example.com",
        cache=mock_cache,
        settings=mock_settings,
    )
    assert c._cache_key_repos() == "quay:https://quay.example.com:myorg:repos"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_closes_quay_api(
    client: QuayWorkspaceClient, mock_quay_api: MagicMock
) -> None:
    with client:
        pass

    mock_quay_api.close.assert_called_once()
