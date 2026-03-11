"""InternalGroupsWorkspaceClient: Caching layer for LDAP group memberships."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from qontract_utils.internal_groups_api import Group, InternalGroupsApi

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedGroup(BaseModel, frozen=True):
    """Cached Group object (for two-tier cache serialization)."""

    item: Group


class InternalGroupsWorkspaceClient:
    """Caching + compute layer for LDAP group memberships.

    Provides:
    - Two-tier caching (memory + Redis) for group member data with TTL
    - Distributed locking for thread-safe cache updates
    """

    def __init__(
        self,
        api: InternalGroupsApi,
        cache: CacheBackend,
        settings: Settings,
        cache_key_prefix: str,
    ) -> None:
        """Initialize InternalGroupsWorkspaceClient.

        Args:
            api: Stateless InternalGroupsApi client
            cache: Cache backend with two-tier caching
            settings: Application settings
            cache_key_prefix: Prefix for cache keys (unique per secret/base_url)
        """
        self.api = api
        self.cache = cache
        self.settings = settings
        self.cache_key_prefix = cache_key_prefix

    def _cache_key(self, group_name: str) -> str:
        return f"ldap:{self.cache_key_prefix}:group:{group_name}:members"

    def get_group(self, group_name: str) -> Group:
        """Get LDAP group members (cached with distributed locking).

        Args:
            group_name: LDAP group name

        Returns:
            Group with members
        """
        cache_key = self._cache_key(group_name)

        if cached := self.cache.get_obj(cache_key, CachedGroup):
            return cached.item

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedGroup):
                return cached.item

            group = self.api.get_group_members(group_name)
            self.cache.set_obj(
                cache_key,
                CachedGroup(item=group),
                self.settings.ldap.groups_cache_ttl,
            )
            return group
