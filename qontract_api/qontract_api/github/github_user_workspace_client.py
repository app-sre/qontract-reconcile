"""GithubUserWorkspaceClient: Caching layer for GitHub user lookups.

This layer sits between the stateless GithubApi.get_user and business
logic, providing per-user caching (including negative caching of 404s) so
repeated validation runs don't re-hit GitHub for the same username.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from qontract_utils.github_api import GithubRateLimitExceededError, GithubUser

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_utils.github_api.api import GithubApi

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)

# Bump when the rate-limit key's format or derivation changes, so stale
# entries under the old format are never misread as valid under the new one.
_RATE_LIMIT_KEY_VERSION = "v1"


class CachedGithubUser(BaseModel, frozen=True):
    """Cached result of a single GitHub user lookup.

    `found=False` represents a cached not-found (404) result, distinct from
    no cache entry at all (meaning "not yet looked up").
    """

    found: bool
    login: str | None = None
    type: str | None = None
    id: int | None = None


class RateLimitMarker(BaseModel, frozen=True):
    """Marks that GitHub's API rate limit was exhausted for this credential.

    Cached with a TTL derived from the rate limit reset time so subsequent
    lookups short-circuit instead of repeating a doomed GitHub call.
    """

    reset_at: datetime


class GithubUserWorkspaceClient:
    """Caching layer for GitHub user lookups (Layer 2).

    Provides per-user caching (positive and negative) of GitHub user lookups,
    plus rate-limit short-circuiting shared across all usernames in a batch.
    """

    def __init__(
        self,
        github_api: GithubApi,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize GithubUserWorkspaceClient.

        Args:
            github_api: Stateless GitHub API client (Layer 1)
            cache: Cache backend with two-tier caching (memory + Redis)
            settings: Application settings with GitHub user cache config
        """
        self._api = github_api
        self._cache = cache
        self._settings = settings

    @staticmethod
    def _cache_key(username: str) -> str:
        return f"github-user:{username.lower()}:info"

    def _rate_limit_key(self) -> str:
        """Scope the rate-limit marker to this client's credential.

        Without this, a rate limit hit by one GitHub token would also
        short-circuit requests made with a different, unaffected token -
        GitHub's rate limits are per-credential, but the cache backend is
        shared across every caller of this endpoint.
        """
        return f"github-user:rate-limited:{_RATE_LIMIT_KEY_VERSION}:{self._api.credential_id}"

    def _cache_rate_limit_marker(self, exc: GithubRateLimitExceededError) -> None:
        """Cache a rate-limit marker so subsequent lookups short-circuit until reset."""
        ttl = max(
            1,
            min(
                int((exc.reset_at - datetime.now(UTC)).total_seconds()),
                self._settings.github_org.user_cache_ttl,
            ),
        )
        self._cache.set_obj(
            self._rate_limit_key(), RateLimitMarker(reset_at=exc.reset_at), ttl
        )

    def _lookup_one(self, username: str) -> GithubUser | None:
        cache_key = self._cache_key(username)
        rate_limit_key = self._rate_limit_key()

        if marker := self._cache.get_obj(rate_limit_key, RateLimitMarker):
            raise GithubRateLimitExceededError(marker.reset_at)

        if (cached := self._cache.get_obj(cache_key, CachedGithubUser)) is not None:
            return self._to_github_user(cached)

        with self._cache.lock(cache_key):
            if marker := self._cache.get_obj(rate_limit_key, RateLimitMarker):
                raise GithubRateLimitExceededError(marker.reset_at)

            if (cached := self._cache.get_obj(cache_key, CachedGithubUser)) is not None:
                return self._to_github_user(cached)

            try:
                user = self._api.get_user(username)
            except GithubRateLimitExceededError as e:
                self._cache_rate_limit_marker(e)
                raise

            if user is None:
                self._cache.set_obj(
                    cache_key,
                    CachedGithubUser(found=False),
                    self._settings.github_org.user_not_found_cache_ttl,
                )
                return None

            self._cache.set_obj(
                cache_key,
                CachedGithubUser(
                    found=True, login=user.login, type=user.type, id=user.id
                ),
                self._settings.github_org.user_cache_ttl,
            )
            return user

    @staticmethod
    def _to_github_user(cached: CachedGithubUser) -> GithubUser | None:
        if not cached.found:
            return None
        assert cached.login is not None
        assert cached.type is not None
        assert cached.id is not None
        return GithubUser(login=cached.login, type=cached.type, id=cached.id)

    def lookup_users(self, usernames: list[str]) -> list[GithubUser]:
        """Look up GitHub users with per-user caching.

        Args:
            usernames: GitHub usernames to look up

        Returns:
            GithubUser for each username that exists. Non-existent usernames
            are omitted - callers must treat a missing username as
            unresolved, not as an error.
        """
        return [
            user
            for username in usernames
            if (user := self._lookup_one(username)) is not None
        ]
