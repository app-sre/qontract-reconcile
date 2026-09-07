"""GithubOrgWorkspaceClient: Caching + compute layer for GitHub org member data.

This layer sits between the stateless GithubOrgApi and business logic, providing:
- Two-tier caching (memory + Redis) for org member lists
- Distributed locking for thread-safe cache updates
- Write-through cache invalidation after mutations
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from qontract_utils.github_org import GithubRateLimitExceededError

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_utils.github_org.api import GithubOrgApi

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedOrgMembers(BaseModel, frozen=True):
    """Cached combined list of admin members + pending invitations."""

    members: list[str] = Field(default_factory=list)


class RateLimitMarker(BaseModel, frozen=True):
    """Marks that GitHub's API rate limit was exhausted for an org's credential.

    Cached with a TTL derived from the rate limit reset time so subsequent
    reconcile cycles short-circuit instead of repeating a doomed GitHub call.
    """

    reset_at: datetime


class GithubOrgWorkspaceClient:
    """Caching + compute layer for GitHub organization member data.

    Provides:
    - Cached access to combined admin members + pending invitations per org
    - Distributed locking for thread-safe cache updates
    - Write-through cache invalidation after member mutations
    """

    def __init__(
        self,
        github_org_api: GithubOrgApi,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize GithubOrgWorkspaceClient.

        Args:
            github_org_api: Stateless GitHub Org API client (Layer 1)
            cache: Cache backend with two-tier caching (memory + Redis)
            settings: Application settings with GitHub org config
        """
        self._api = github_org_api
        self._cache = cache
        self._settings = settings

    @staticmethod
    def _cache_key(org_name: str) -> str:
        return f"github-org:{org_name}:members"

    @staticmethod
    def _rate_limit_key(org_name: str) -> str:
        return f"github-org:{org_name}:rate-limited"

    def _clear_cache(self, org_name: str) -> None:
        """Clear cached members for the given org."""
        cache_key = self._cache_key(org_name)
        try:
            with self._cache.lock(cache_key):
                self._cache.delete(cache_key)
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock to clear cache for {org_name}: {e}")

    def get_current_members(self, org_name: str) -> list[str]:
        """Get the combined set of admin members + pending invitations (cached).

        Combines admin members and pending invitations into a single deduplicated
        sorted list. Both lists are lowercased for case-insensitive comparison.

        Args:
            org_name: GitHub organization name

        Returns:
            Sorted list of lowercase GitHub usernames (admins + pending invitees)
        """
        cache_key = self._cache_key(org_name)

        if cached := self._cache.get_obj(cache_key, CachedOrgMembers):
            return cached.members

        rate_limit_key = self._rate_limit_key(org_name)
        if marker := self._cache.get_obj(rate_limit_key, RateLimitMarker):
            raise GithubRateLimitExceededError(marker.reset_at)

        with self._cache.lock(cache_key):
            if cached := self._cache.get_obj(cache_key, CachedOrgMembers):
                return cached.members

            try:
                admin_members = self._api.get_admin_members(org_name)
                pending_invitations = self._api.get_pending_invitations(org_name)
            except GithubRateLimitExceededError as e:
                ttl = max(
                    1,
                    min(
                        int((e.reset_at - datetime.now(UTC)).total_seconds()),
                        self._settings.github_org.members_cache_ttl,
                    ),
                )
                self._cache.set_obj(
                    rate_limit_key,
                    RateLimitMarker(reset_at=e.reset_at),
                    ttl,
                )
                raise

            combined = sorted(set(admin_members) | set(pending_invitations))
            cached_obj = CachedOrgMembers(members=combined)
            self._cache.set_obj(
                cache_key,
                cached_obj,
                self._settings.github_org.members_cache_ttl,
            )
            return combined

    def add_member_as_admin(self, org_name: str, username: str) -> None:
        """Add a user as org admin and invalidate the member cache.

        Args:
            org_name: GitHub organization name
            username: GitHub username to add as admin
        """
        self._api.add_member_as_admin(org_name, username)
        self._clear_cache(org_name)
