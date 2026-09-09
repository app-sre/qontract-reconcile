"""LdapWorkspaceClient: Caching layer for direct LDAP user operations (FreeIPA)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from pydantic import BaseModel

from qontract_api.external.ldap.schemas import LdapUserStatus
from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_utils.ldap_api import LdapApi

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedUserCheck(BaseModel, frozen=True):
    """Cached user existence check result (for two-tier cache serialization)."""

    result: list[LdapUserStatus]


class CachedGithubUsernames(BaseModel, frozen=True):
    """Cached GitHub-login -> uid(s) map (for two-tier cache serialization).

    Each lowercased login maps to the sorted list of uids that claim it; a login
    with more than one uid is ambiguous and resolved (skipped + logged) per
    request, not at build time.
    """

    mapping: dict[str, list[str]]


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

    def _github_usernames_cache_key(self) -> str:
        """Cache key for the full GitHub-username -> uid map of this server."""
        return f"ldap:{self.cache_key_prefix}:github-usernames"

    def _get_github_username_map(self) -> dict[str, list[str]]:
        """Return the full GitHub-login -> uid(s) map (cached, locked)."""
        cache_key = self._github_usernames_cache_key()

        if cached := self.cache.get_obj(cache_key, CachedGithubUsernames):
            return cached.mapping

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedGithubUsernames):
                return cached.mapping

            with self.api:
                mapping = self.api.get_github_usernames()

            self.cache.set_obj(
                cache_key,
                CachedGithubUsernames(mapping=mapping),
                ttl=self.settings.ldap.github_usernames_cache_ttl,
            )
            return mapping

    def resolve_github_usernames(self, logins: Iterable[str]) -> dict[str, str]:
        """Resolve GitHub usernames to LDAP uids via rhatSocialURL (cached).

        The full GitHub-login -> uid(s) map is fetched from LDAP once per TTL
        window and cached; individual lookups are then served from it. Matching
        is case-insensitive (GitHub logins are), and only requested logins found
        in LDAP are returned - unresolved logins are omitted.

        A requested login that maps to more than one uid is ambiguous: LDAP
        result order must not decide identity, so it is skipped and logged. The
        ambiguity check is scoped to the *requested* logins, so unrelated
        ambiguous directory entries (organizations/repos claimed by several
        associates) never appear in the logs.

        Args:
            logins: GitHub usernames to resolve

        Returns:
            Mapping of the requested GitHub username to its LDAP uid
            (app-interface org_username)
        """
        requested = set(logins)
        if not requested:
            return {}

        mapping = self._get_github_username_map()

        resolved: dict[str, str] = {}
        for login in requested:
            if not (uids := mapping.get(login.lower())):
                continue
            if len(uids) > 1:
                logger.warning(
                    "Ambiguous GitHub login maps to multiple LDAP uids; skipping",
                    github_login=login,
                    uids=uids,
                )
                continue
            resolved[login] = uids[0]
        return resolved
