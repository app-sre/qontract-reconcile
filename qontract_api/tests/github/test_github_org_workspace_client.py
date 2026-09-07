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
    mock_cache.get_obj.return_value = CachedOrgMembers(members=["alice"])

    members = client.get_current_members(ORG_NAME)

    assert members == ["alice"]
    assert mock_cache.get_obj.call_count == 1
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
    mock_cache.get_obj.side_effect = [None, RateLimitMarker(reset_at=reset_at)]

    with pytest.raises(GithubRateLimitExceededError) as exc_info:
        client.get_current_members(ORG_NAME)

    assert exc_info.value.reset_at == reset_at
    mock_cache.lock.assert_not_called()
    mock_github_org_api.get_admin_members.assert_not_called()
    mock_github_org_api.get_pending_invitations.assert_not_called()


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
