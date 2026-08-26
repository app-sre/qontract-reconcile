"""QuayWorkspaceClient: Caching + compute layer for Quay robot-account data.

This layer sits between the stateless QuayApi and business logic, providing:
- Two-tier caching (memory + Redis) for robot lists and permissions
- Distributed locking for thread-safe cache updates
- Write-through cache invalidation after mutations
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from qontract_utils.quay_api.models import RobotAccount, RobotAccountPermission

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_utils.quay_api import QuayApi

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedRobotAccounts(BaseModel, frozen=True):
    """Cached list of robot accounts for an organization."""

    items: list[RobotAccount] = Field(default_factory=list)


class CachedRobotPermissions(BaseModel, frozen=True):
    """Cached list of repository permissions for a robot."""

    items: list[RobotAccountPermission] = Field(default_factory=list)


class QuayWorkspaceClient:
    """Caching + compute layer for Quay robot-account operations.

    Bound to a single Quay instance + organization (matching Layer 1 QuayApi).
    """

    def __init__(
        self,
        quay_api: QuayApi,
        instance_name: str,
        organization: str,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        self._api = quay_api
        self.instance_name = instance_name
        self.organization = organization
        self._cache = cache
        self._settings = settings

    def _robots_cache_key(self) -> str:
        return f"quay:{self.instance_name}:{self.organization}:robots"

    def _permissions_cache_key(self, robot_name: str) -> str:
        return f"quay:{self.instance_name}:{self.organization}:robot:{robot_name}:permissions"

    def _clear_cache(self, cache_key: str) -> None:
        try:
            with self._cache.lock(cache_key):
                self._cache.delete(cache_key)
        except RuntimeError as e:
            logger.warning(
                f"Could not acquire lock to clear cache for {cache_key}: {e}"
            )
            raise

    def list_robot_accounts(self) -> list[RobotAccount]:
        """List robot accounts for this org (cached)."""
        cache_key = self._robots_cache_key()

        if cached := self._cache.get_obj(cache_key, CachedRobotAccounts):
            return cached.items

        with self._cache.lock(cache_key):
            if cached := self._cache.get_obj(cache_key, CachedRobotAccounts):
                return cached.items

            robots = self._api.list_robot_accounts()
            self._cache.set_obj(
                cache_key,
                CachedRobotAccounts(items=robots),
                self._settings.quay.robots_cache_ttl,
            )
            return robots

    def get_robot_account_permissions(
        self, robot_name: str
    ) -> list[RobotAccountPermission]:
        """List repository permissions for a robot (cached)."""
        cache_key = self._permissions_cache_key(robot_name)

        if cached := self._cache.get_obj(cache_key, CachedRobotPermissions):
            return cached.items

        with self._cache.lock(cache_key):
            if cached := self._cache.get_obj(cache_key, CachedRobotPermissions):
                return cached.items

            permissions = self._api.get_robot_account_permissions(robot_name)
            self._cache.set_obj(
                cache_key,
                CachedRobotPermissions(items=permissions),
                self._settings.quay.robots_cache_ttl,
            )
            return permissions

    def create_robot_account(self, name: str, description: str) -> None:
        """Create a robot and invalidate the org robot list cache."""
        self._api.create_robot_account(name, description)
        self._clear_cache(self._robots_cache_key())

    def delete_robot_account(self, name: str) -> None:
        """Delete a robot and invalidate related caches."""
        self._api.delete_robot_account(name)
        self._clear_cache(self._robots_cache_key())
        self._clear_cache(self._permissions_cache_key(name))

    def add_robot_to_team(self, robot_name: str, team: str) -> None:
        """Add a robot to a team (short name) and invalidate the robot list."""
        self._api.add_user_to_team(f"{self.organization}+{robot_name}", team)
        self._clear_cache(self._robots_cache_key())

    def remove_robot_from_team(self, robot_name: str, team: str) -> None:
        """Remove a robot from a team without dropping org membership."""
        self._api.remove_robot_from_team(robot_name, team)
        self._clear_cache(self._robots_cache_key())

    def set_repo_robot_account_permissions(
        self, repo_name: str, robot_name: str, role: str
    ) -> None:
        """Set a robot's repository role and invalidate permission cache."""
        self._api.set_repo_robot_account_permissions(repo_name, robot_name, role)
        self._clear_cache(self._permissions_cache_key(robot_name))

    def delete_repo_robot_account_permissions(
        self, repo_name: str, robot_name: str
    ) -> None:
        """Remove a robot's repository permission and invalidate cache."""
        self._api.delete_repo_robot_account_permissions(repo_name, robot_name)
        self._clear_cache(self._permissions_cache_key(robot_name))

    def close(self) -> None:
        """Close the underlying Layer 1 HTTP client."""
        self._api.close()
