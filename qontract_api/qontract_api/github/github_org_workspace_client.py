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
    def _all_members_cache_key(org_name: str) -> str:
        return f"github-org:{org_name}:all-members"

    @staticmethod
    def _rate_limit_key(org_name: str) -> str:
        return f"github-org:{org_name}:rate-limited"

    def _clear_cache(self, org_name: str) -> None:
        """Clear both cached member lists for the given org.

        A mutation changes both the admins/invitations list (``:members``) and
        the full membership list (``:all-members``), so both keys must be
        invalidated - each under a lock scoped to that key.
        """
        for cache_key in (
            self._cache_key(org_name),
            self._all_members_cache_key(org_name),
        ):
            try:
                with self._cache.lock(cache_key):
                    self._cache.delete(cache_key)
            except RuntimeError as e:
                logger.warning(
                    f"Could not acquire lock to clear cache for {org_name}: {e}"
                )

    def _cache_rate_limit_marker(
        self, org_name: str, exc: GithubRateLimitExceededError
    ) -> None:
        """Cache a rate-limit marker so subsequent calls short-circuit until reset."""
        ttl = max(
            1,
            min(
                int((exc.reset_at - datetime.now(UTC)).total_seconds()),
                self._settings.github_org.members_cache_ttl,
            ),
        )
        self._cache.set_obj(
            self._rate_limit_key(org_name),
            RateLimitMarker(reset_at=exc.reset_at),
            ttl,
        )

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
        rate_limit_key = self._rate_limit_key(org_name)

        if marker := self._cache.get_obj(rate_limit_key, RateLimitMarker):
            raise GithubRateLimitExceededError(marker.reset_at)

        if cached := self._cache.get_obj(cache_key, CachedOrgMembers):
            return cached.members

        with self._cache.lock(cache_key):
            if marker := self._cache.get_obj(rate_limit_key, RateLimitMarker):
                raise GithubRateLimitExceededError(marker.reset_at)

            if cached := self._cache.get_obj(cache_key, CachedOrgMembers):
                return cached.members

            try:
                admin_members = self._api.get_admin_members(org_name)
                pending_invitations = self._api.get_pending_invitations(org_name)
            except GithubRateLimitExceededError as e:
                self._cache_rate_limit_marker(org_name, e)
                raise

            combined = sorted(set(admin_members) | set(pending_invitations))
            cached_obj = CachedOrgMembers(members=combined)
            self._cache.set_obj(
                cache_key,
                cached_obj,
                self._settings.github_org.members_cache_ttl,
            )
            return combined

    def get_all_members(self, org_name: str) -> list[str]:
        """Get all organization members (any role), cached.

        Unlike `get_current_members` (admins + pending invitations), this
        returns every member of the organization. Logins are returned in their
        original case exactly as GitHub reports them; callers that need
        case-insensitive comparison must lowercase on their side.

        Args:
            org_name: GitHub organization name

        Returns:
            Sorted list of GitHub usernames (original case) of all org members
        """
        cache_key = self._all_members_cache_key(org_name)
        rate_limit_key = self._rate_limit_key(org_name)

        if marker := self._cache.get_obj(rate_limit_key, RateLimitMarker):
            raise GithubRateLimitExceededError(marker.reset_at)

        if cached := self._cache.get_obj(cache_key, CachedOrgMembers):
            return cached.members

        with self._cache.lock(cache_key):
            if marker := self._cache.get_obj(rate_limit_key, RateLimitMarker):
                raise GithubRateLimitExceededError(marker.reset_at)

            if cached := self._cache.get_obj(cache_key, CachedOrgMembers):
                return cached.members

            try:
                members = self._api.get_members(org_name)
            except GithubRateLimitExceededError as e:
                self._cache_rate_limit_marker(org_name, e)
                raise

            self._cache.set_obj(
                cache_key,
                CachedOrgMembers(members=members),
                self._settings.github_org.members_cache_ttl,
            )
            return members

    def add_member_as_admin(self, org_name: str, username: str) -> None:
        """Add a user as org admin and invalidate the member cache.

        Args:
            org_name: GitHub organization name
            username: GitHub username to add as admin
        """
        try:
            self._api.add_member_as_admin(org_name, username)
        except GithubRateLimitExceededError as e:
            self._cache_rate_limit_marker(org_name, e)
            raise
        self._clear_cache(org_name)
