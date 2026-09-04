"""QuayWorkspaceClient: Caching layer for Quay organization data.

Layer 2 (Cache + Compute) following ADR-014. Sits between the stateless
QuayApi (Layer 1) and business logic (Layer 3), providing:
- Two-tier caching (memory + Redis) with TTL
- Distributed locking for thread-safe cache updates
- Cache invalidation after each successful mutation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, Field
from qontract_utils.quay_api import QuayApi, QuayRepo
from qontract_utils.quay_api.models import RobotAccount, RobotAccountPermission

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedRepos(BaseModel, frozen=True):
    """Serializable wrapper for a list of QuayRepo objects."""

    items: list[QuayRepo] = Field(default_factory=list)


class CachedRobotAccounts(BaseModel, frozen=True):
    """Cached list of robot accounts for an organization."""

    items: list[RobotAccount] = Field(default_factory=list)


class CachedRobotPermissions(BaseModel, frozen=True):
    """Cached list of repository permissions for a robot."""

    items: list[RobotAccountPermission] = Field(default_factory=list)


class QuayWorkspaceClient:
    """Caching layer for Quay organization repository and robot-account data.

    Provides:
    - Cached access to repository lists, robots, and permissions with TTL
    - Distributed locking for thread-safe cache updates
    - Cache invalidation after each successful mutation
    """

    def __init__(
        self,
        quay_api: QuayApi,
        base_url: str,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        self.quay_api = quay_api
        self._base_url = base_url.rstrip("/")
        self.cache = cache
        self.settings = settings

    def _cache_key_repos(self) -> str:
        return f"quay:{self._base_url}:{self.quay_api.org}:repos"

    def _robots_cache_key(self) -> str:
        return f"quay:{self._base_url}:{self.quay_api.org}:robots"

    def _permissions_cache_key(self, robot_name: str) -> str:
        return (
            f"quay:{self._base_url}:{self.quay_api.org}:robot:{robot_name}:permissions"
        )

    def _clear_cache(self, cache_key: str) -> None:
        """Invalidate a cache key after a successful Quay mutation.

        Lock failures are logged and swallowed: the mutation is already
        committed, and a later reconcile refreshes the entry after TTL.
        """
        try:
            with self.cache.lock(cache_key):
                self.cache.delete(cache_key)
        except RuntimeError as e:
            logger.warning(
                f"Could not acquire lock to clear cache for {cache_key}: {e}"
            )

    # ------------------------------------------------------------------
    # Cached reads
    # ------------------------------------------------------------------

    def get_repos(self) -> list[QuayRepo]:
        """List all repositories in the organization (cached).

        Returns:
            List of QuayRepo objects
        """
        cache_key = self._cache_key_repos()

        cached = self.cache.get_obj(cache_key, CachedRepos)
        if cached:
            return cached.items

        with self.cache.lock(cache_key):
            cached = self.cache.get_obj(cache_key, CachedRepos)
            if cached:
                return cached.items

            repos = self.quay_api.list_images()
            self.cache.set_obj(
                cache_key,
                CachedRepos(items=repos),
                self.settings.quay.repos_cache_ttl,
            )
            return repos

    def list_robot_accounts(self) -> list[RobotAccount]:
        """List robot accounts for this org (cached)."""
        cache_key = self._robots_cache_key()

        if cached := self.cache.get_obj(cache_key, CachedRobotAccounts):
            return cached.items

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedRobotAccounts):
                return cached.items

            robots = self.quay_api.list_robot_accounts()
            self.cache.set_obj(
                cache_key,
                CachedRobotAccounts(items=robots),
                self.settings.quay.robots_cache_ttl,
            )
            return robots

    def get_robot_account_permissions(
        self, robot_name: str
    ) -> list[RobotAccountPermission]:
        """List repository permissions for a robot (cached)."""
        cache_key = self._permissions_cache_key(robot_name)

        if cached := self.cache.get_obj(cache_key, CachedRobotPermissions):
            return cached.items

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedRobotPermissions):
                return cached.items

            permissions = self.quay_api.get_robot_account_permissions(robot_name)
            self.cache.set_obj(
                cache_key,
                CachedRobotPermissions(items=permissions),
                self.settings.quay.robots_cache_ttl,
            )
            return permissions

    # ------------------------------------------------------------------
    # Repository mutations
    # ------------------------------------------------------------------

    def repo_create(self, repo_name: str, description: str, *, public: bool) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_create(repo_name, description, public=public)
            self.cache.delete(cache_key)

    def repo_delete(self, repo_name: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_delete(repo_name)
            self.cache.delete(cache_key)

    def repo_update_description(self, repo_name: str, description: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_update_description(repo_name, description)
            self.cache.delete(cache_key)

    def repo_make_public(self, repo_name: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_make_public(repo_name)
            self.cache.delete(cache_key)

    def repo_make_private(self, repo_name: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_make_private(repo_name)
            self.cache.delete(cache_key)

    # ------------------------------------------------------------------
    # Robot-account mutations
    # ------------------------------------------------------------------

    def create_robot_account(self, name: str, description: str) -> None:
        """Create a robot and invalidate the org robot list cache."""
        self.quay_api.create_robot_account(name, description)
        self._clear_cache(self._robots_cache_key())

    def delete_robot_account(self, name: str) -> None:
        """Delete a robot and invalidate related caches."""
        self.quay_api.delete_robot_account(name)
        self._clear_cache(self._robots_cache_key())
        self._clear_cache(self._permissions_cache_key(name))

    def add_robot_to_team(self, robot_name: str, team: str) -> None:
        """Add a robot to a team (short name) and invalidate the robot list."""
        self.quay_api.add_user_to_team(f"{self.quay_api.org}+{robot_name}", team)
        self._clear_cache(self._robots_cache_key())

    def remove_robot_from_team(self, robot_name: str, team: str) -> None:
        """Remove a robot from a team without dropping org membership."""
        self.quay_api.remove_robot_from_team(robot_name, team)
        self._clear_cache(self._robots_cache_key())

    def set_repo_robot_account_permissions(
        self, repo_name: str, robot_name: str, role: str
    ) -> None:
        """Set a robot's repository role and invalidate permission cache."""
        self.quay_api.set_repo_robot_account_permissions(repo_name, robot_name, role)
        self._clear_cache(self._permissions_cache_key(robot_name))

    def delete_repo_robot_account_permissions(
        self, repo_name: str, robot_name: str
    ) -> None:
        """Remove a robot's repository permission and invalidate cache."""
        self.quay_api.delete_repo_robot_account_permissions(repo_name, robot_name)
        self._clear_cache(self._permissions_cache_key(robot_name))

    def close(self) -> None:
        self.quay_api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
