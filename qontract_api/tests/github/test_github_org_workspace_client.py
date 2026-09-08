"""Unit tests for GithubOrgWorkspaceClient."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.github_org import GithubRateLimitExceededError

from qontract_api.github.github_org_workspace_client import (
    CachedOrgMembers,
    GithubOrgWorkspaceClient,
    RateLimitMarker,
)

if TYPE_CHECKING:
    from qontract_api.config import Settings

ORG_NAME = "my-org"


@pytest.fixture
def client(
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> GithubOrgWorkspaceClient:
    return GithubOrgWorkspaceClient(
        github_org_api=mock_github_org_api,
        cache=mock_cache,
        settings=mock_settings,
    )


# ---------------------------------------------------------------------------
# get_current_members — members cache hit (regression)
# ---------------------------------------------------------------------------


def test_members_cache_hit_still_returns(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.side_effect = [None, CachedOrgMembers(members=["alice"])]

    members = client.get_current_members(ORG_NAME)

    assert members == ["alice"]
    assert mock_cache.get_obj.call_count == 2
    mock_cache.lock.assert_not_called()
    mock_github_org_api.get_admin_members.assert_not_called()
    mock_github_org_api.get_pending_invitations.assert_not_called()


# ---------------------------------------------------------------------------
# get_current_members — rate limit while fetching from GitHub
# ---------------------------------------------------------------------------


def test_sets_marker_and_reraises_on_rate_limit(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=120)
    mock_github_org_api.get_admin_members.side_effect = GithubRateLimitExceededError(
        reset_at
    )

    with pytest.raises(GithubRateLimitExceededError):
        client.get_current_members(ORG_NAME)

    mock_cache.set_obj.assert_called_once()
    key, marker, _ttl = mock_cache.set_obj.call_args[0]
    assert key == f"github-org:{ORG_NAME}:rate-limited"
    assert marker == RateLimitMarker(reset_at=reset_at)


def test_marker_ttl_derived_from_reset(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=120)
    mock_github_org_api.get_admin_members.side_effect = GithubRateLimitExceededError(
        reset_at
    )

    with pytest.raises(GithubRateLimitExceededError):
        client.get_current_members(ORG_NAME)

    ttl = mock_cache.set_obj.call_args[0][2]
    assert 110 <= ttl <= 120


def test_marker_ttl_capped_at_members_cache_ttl(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=100_000)
    mock_github_org_api.get_admin_members.side_effect = GithubRateLimitExceededError(
        reset_at
    )

    with pytest.raises(GithubRateLimitExceededError):
        client.get_current_members(ORG_NAME)

    ttl = mock_cache.set_obj.call_args[0][2]
    assert ttl == mock_settings.github_org.members_cache_ttl


def test_short_circuits_when_marker_present(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=60)
    mock_cache.get_obj.side_effect = [RateLimitMarker(reset_at=reset_at)]

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        client.get_current_members(ORG_NAME)

    assert exc_info.value.reset_at == reset_at
    mock_cache.lock.assert_not_called()
    mock_github_org_api.get_admin_members.assert_not_called()
    mock_github_org_api.get_pending_invitations.assert_not_called()


def test_marker_takes_priority_over_stale_members_cache(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """A rate-limit marker must short-circuit even when a stale members cache exists.

    A write hitting the rate limit caches the marker but does not clear the
    (still valid) members cache. If the members-cache lookup ran first, it
    would return the stale list without ever consulting the marker, so the
    org would not be skipped and the same doomed mutation would be retried.
    """
    reset_at = datetime.now(UTC) + timedelta(seconds=60)
    mock_cache.get_obj.side_effect = [
        RateLimitMarker(reset_at=reset_at),
        CachedOrgMembers(members=["alice"]),
    ]

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        client.get_current_members(ORG_NAME)

    assert exc_info.value.reset_at == reset_at
    mock_cache.lock.assert_not_called()
    mock_github_org_api.get_admin_members.assert_not_called()
    mock_github_org_api.get_pending_invitations.assert_not_called()


def test_marker_rechecked_after_acquiring_lock(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """A marker written while waiting on the lock must still short-circuit.

    Simulates: no marker and no cached members before the lock, but by the
    time the lock is acquired another caller has already cached the marker
    (e.g. a concurrent write just hit the rate limit).
    """
    reset_at = datetime.now(UTC) + timedelta(seconds=60)
    mock_cache.get_obj.side_effect = [
        None,  # marker check before member-cache hit
        None,  # member-cache check before lock
        RateLimitMarker(reset_at=reset_at),  # marker recheck after acquiring lock
    ]

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        client.get_current_members(ORG_NAME)

    assert exc_info.value.reset_at == reset_at
    mock_github_org_api.get_admin_members.assert_not_called()
    mock_github_org_api.get_pending_invitations.assert_not_called()


# ---------------------------------------------------------------------------
# get_all_members — all org members (any role)
# ---------------------------------------------------------------------------


def test_get_all_members_cache_miss_fetches_and_caches(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_github_org_api.get_members.return_value = ["Bob", "alice"]

    members = client.get_all_members(ORG_NAME)

    # returned verbatim from the API (case preserved, no lowercasing here)
    assert members == ["Bob", "alice"]
    mock_github_org_api.get_members.assert_called_once_with(ORG_NAME)
    key, cached_obj, ttl = mock_cache.set_obj.call_args[0]
    assert key == f"github-org:{ORG_NAME}:all-members"
    assert cached_obj == CachedOrgMembers(members=["Bob", "alice"])
    assert ttl == mock_settings.github_org.members_cache_ttl


def test_get_all_members_cache_hit_skips_api(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_cache.get_obj.side_effect = [None, CachedOrgMembers(members=["alice"])]

    members = client.get_all_members(ORG_NAME)

    assert members == ["alice"]
    mock_cache.lock.assert_not_called()
    mock_github_org_api.get_members.assert_not_called()


def test_get_all_members_short_circuits_when_marker_present(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=60)
    mock_cache.get_obj.side_effect = [RateLimitMarker(reset_at=reset_at)]

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        client.get_all_members(ORG_NAME)

    assert exc_info.value.reset_at == reset_at
    mock_cache.lock.assert_not_called()
    mock_github_org_api.get_members.assert_not_called()


def test_get_all_members_sets_marker_and_reraises_on_rate_limit(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=120)
    mock_github_org_api.get_members.side_effect = GithubRateLimitExceededError(reset_at)

    with pytest.raises(GithubRateLimitExceededError):
        client.get_all_members(ORG_NAME)

    key, marker, _ttl = mock_cache.set_obj.call_args[0]
    assert key == f"github-org:{ORG_NAME}:rate-limited"
    assert marker == RateLimitMarker(reset_at=reset_at)


# ---------------------------------------------------------------------------
# add_member_as_admin — rate limit while applying a mutation
# ---------------------------------------------------------------------------


def test_add_member_as_admin_sets_marker_and_reraises_on_rate_limit(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """A rate limit hit while applying a mutation must also cache the marker.

    Otherwise the next cycle reuses the (already-cached) stale member list
    and regenerates the same doomed action - the mitigation would only cover
    the read path, not the write path.
    """
    reset_at = datetime.now(UTC) + timedelta(seconds=120)
    mock_github_org_api.add_member_as_admin.side_effect = GithubRateLimitExceededError(
        reset_at
    )

    with pytest.raises(GithubRateLimitExceededError):
        client.add_member_as_admin(ORG_NAME, "alice")

    mock_cache.set_obj.assert_called_once()
    key, marker, _ttl = mock_cache.set_obj.call_args[0]
    assert key == f"github-org:{ORG_NAME}:rate-limited"
    assert marker == RateLimitMarker(reset_at=reset_at)


def test_add_member_as_admin_does_not_clear_members_cache_on_rate_limit(
    client: GithubOrgWorkspaceClient,
    mock_github_org_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    reset_at = datetime.now(UTC) + timedelta(seconds=120)
    mock_github_org_api.add_member_as_admin.side_effect = GithubRateLimitExceededError(
        reset_at
    )

    with pytest.raises(GithubRateLimitExceededError):
        client.add_member_as_admin(ORG_NAME, "alice")

    mock_cache.delete.assert_not_called()
