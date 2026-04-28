"""LdapWorkspaceClient: Caching layer for direct LDAP user operations (FreeIPA)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import BaseModel
from qontract_utils.ldap_api import LdapApi

from qontract_api.external.ldap.schemas import LdapUserStatus
from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedUserCheck(BaseModel, frozen=True):
    """Cached user existence check result (for two-tier cache serialization)."""

    result: list[LdapUserStatus]


class LdapWorkspaceClient:
    """Caching + locking layer for direct LDAP operations (FreeIPA).

    Provides:
    - Two-tier caching (memory + Redis) for user existence checks with TTL
    - Distributed locking for thread-safe cache updates (double-check pattern)
    - Uses LdapApi (Layer 1) as context manager for connection lifecycle
    """

    def __init__(
        self,
        api: LdapApi,
        cache: CacheBackend,
        settings: Settings,
        cache_key_prefix: str,
    ) -> None:
        """Initialize LdapWorkspaceClient.

        Args:
            api: Stateless LdapApi client (Layer 1)
            cache: Cache backend with two-tier caching
            settings: Application settings
            cache_key_prefix: Prefix for cache keys (unique per LDAP server)
        """
        self.api = api
        self.cache = cache
        self.settings = settings
        self.cache_key_prefix = cache_key_prefix

    def _cache_key(self, usernames: Iterable[str]) -> str:
        """Generate a deterministic cache key for a set of usernames."""
        sorted_names = ",".join(sorted(usernames))
        name_hash = hashlib.sha256(sorted_names.encode()).hexdigest()[:16]
        return f"ldap:{self.cache_key_prefix}:users:check:{name_hash}"

    def check_users_exist(self, usernames: Iterable[str]) -> list[LdapUserStatus]:
        """Check which usernames exist in LDAP (cached with distributed locking).

        Uses double-check locking pattern to minimize lock contention.
        The LdapApi is used as a context manager to bind/unbind per request.

        Args:
            usernames: Usernames to check

        Returns:
            List of LdapUserStatus models with username and exists flag
        """
        username_list = set(usernames)
        if not username_list:
            return []

        cache_key = self._cache_key(username_list)

        if cached := self.cache.get_obj(cache_key, CachedUserCheck):
            return cached.result

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedUserCheck):
                return cached.result

            with self.api:
                existing_users = {u.username for u in self.api.get_users(username_list)}

            result = [
                LdapUserStatus(username=u, exists=u in existing_users)
                for u in username_list
            ]

            self.cache.set_obj(
                cache_key,
                CachedUserCheck(result=result),
                ttl=self.settings.ldap.users_cache_ttl,
            )
            return result
