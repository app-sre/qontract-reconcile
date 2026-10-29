"""Unit tests for GithubUserWorkspaceClient."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.github_api import GithubRateLimitExceededError, GithubUser

from qontract_api.github.github_user_workspace_client import (
    CachedGithubUser,
    GithubUserWorkspaceClient,
    RateLimitMarker,
)

if TYPE_CHECKING:
    from qontract_api.config import Settings


@pytest.fixture
def client(
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> GithubUserWorkspaceClient:
    return GithubUserWorkspaceClient(
        github_api=mock_github_api,
        cache=mock_cache,
        settings=mock_settings,
    )


# ---------------------------------------------------------------------------
# lookup_users — cache miss, fetch and cache
# ---------------------------------------------------------------------------


def test_lookup_users_cache_miss_fetches_and_caches(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_github_api.get_user.return_value = GithubUser(
        login="ChunxiAlexLuo", type="User", id=1
    )

    result = client.lookup_users(["chunxialexluo"])

    assert result == [GithubUser(login="ChunxiAlexLuo", type="User", id=1)]
    mock_github_api.get_user.assert_called_once_with("chunxialexluo")
    key, cached_obj, ttl = mock_cache.set_obj.call_args[0]
    assert key == "github-user:chunxialexluo:info"
    assert cached_obj == CachedGithubUser(
        found=True, login="ChunxiAlexLuo", type="User", id=1
    )
    assert ttl == mock_settings.github_org.user_cache_ttl


def test_lookup_users_cache_hit_skips_api(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.side_effect = [
        None,  # marker check
        CachedGithubUser(found=True, login="alice", type="User", id=1),
    ]

    result = client.lookup_users(["alice"])

    assert result == [GithubUser(login="alice", type="User", id=1)]
    mock_cache.lock.assert_not_called()
    mock_github_api.get_user.assert_not_called()


# ---------------------------------------------------------------------------
# lookup_users — not found (negative caching)
# ---------------------------------------------------------------------------


def test_lookup_users_omits_nonexistent_username(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_github_api.get_user.return_value = None

    result = client.lookup_users(["mnovak1"])

    assert result == []
    key, cached_obj, ttl = mock_cache.set_obj.call_args[0]
    assert key == "github-user:mnovak1:info"
    assert cached_obj == CachedGithubUser(found=False)
    assert ttl == mock_settings.github_org.user_not_found_cache_ttl


def test_lookup_users_cached_not_found_skips_api(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.side_effect = [
        None,  # marker check
        CachedGithubUser(found=False),
    ]

    result = client.lookup_users(["mnovak1"])

    assert result == []
    mock_cache.lock.assert_not_called()
    mock_github_api.get_user.assert_not_called()


def test_lookup_users_processes_mixed_results(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
) -> None:
    """A batch with existing and non-existent usernames returns only the found ones."""
    mock_github_api.get_user.side_effect = [
        GithubUser(login="alice", type="User", id=1),
        None,
        GithubUser(login="app-sre", type="Organization", id=2),
    ]

    result = client.lookup_users(["alice", "mnovak1", "app-sre"])

    assert result == [
        GithubUser(login="alice", type="User", id=1),
        GithubUser(login="app-sre", type="Organization", id=2),
    ]


# ---------------------------------------------------------------------------
# lookup_users — rate limit handling
# ---------------------------------------------------------------------------


def test_sets_marker_and_reraises_on_rate_limit(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=120)
    mock_github_api.get_user.side_effect = GithubRateLimitExceededError(reset_at)

    with pytest.raises(GithubRateLimitExceededError):
        client.lookup_users(["alice"])

    key, marker, _ttl = mock_cache.set_obj.call_args[0]
    assert key == "github-user:rate-limited"
    assert marker == RateLimitMarker(reset_at=reset_at)


def test_marker_ttl_derived_from_reset(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=120)
    mock_github_api.get_user.side_effect = GithubRateLimitExceededError(reset_at)

    with pytest.raises(GithubRateLimitExceededError):
        client.lookup_users(["alice"])

    ttl = mock_cache.set_obj.call_args[0][2]
    assert 110 <= ttl <= 120


def test_marker_ttl_capped_at_user_cache_ttl(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=100_000)
    mock_github_api.get_user.side_effect = GithubRateLimitExceededError(reset_at)

    with pytest.raises(GithubRateLimitExceededError):
        client.lookup_users(["alice"])

    ttl = mock_cache.set_obj.call_args[0][2]
    assert ttl == mock_settings.github_org.user_cache_ttl


def test_short_circuits_when_marker_present(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=60)
    mock_cache.get_obj.side_effect = [RateLimitMarker(reset_at=reset_at)]

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        client.lookup_users(["alice"])

    assert exc_info.value.reset_at == reset_at
    mock_cache.lock.assert_not_called()
    mock_github_api.get_user.assert_not_called()


def test_marker_rechecked_after_acquiring_lock(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=60)
    mock_cache.get_obj.side_effect = [
        None,  # marker check before user-cache hit
        None,  # user-cache check before lock
        RateLimitMarker(reset_at=reset_at),  # marker recheck after acquiring lock
    ]

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        client.lookup_users(["alice"])

    assert exc_info.value.reset_at == reset_at
    mock_github_api.get_user.assert_not_called()


def test_rate_limit_mid_batch_stops_remaining_lookups(
    client: GithubUserWorkspaceClient,
    mock_github_api: MagicMock,
) -> None:
    """A rate limit hit on one username must abort the rest of the batch."""
    mock_github_api.get_user.side_effect = [
        GithubUser(login="alice", type="User", id=1),
        GithubRateLimitExceededError(datetime.now(UTC) + timedelta(seconds=60)),
    ]

    with pytest.raises(GithubRateLimitExceededError):
        client.lookup_users(["alice", "bob", "charlie"])

    assert mock_github_api.get_user.call_count == 2
