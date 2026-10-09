"""LdapWorkspaceClient: Caching layer for direct LDAP user operations (FreeIPA)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import BaseModel

from qontract_api.exceptions import ValidationError
from qontract_api.external.ldap.schemas import (
    LdapGroupMember,
    LdapGroupResult,
    LdapUserStatus,
)
from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_utils.ldap_api import LdapApi
    from qontract_utils.ldap_api.models import LdapUser

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


class CachedGroupMembers(BaseModel, frozen=True):
    """Cached LDAP group membership resolution (for two-tier cache serialization)."""

    groups: list[LdapGroupResult]


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

    def _get_org_username_to_github_map(self) -> dict[str, str]:
        """Invert the GitHub-login -> uid(s) map to org_username -> GitHub login.

        Shared logins and org_usernames claiming multiple distinct logins are
        ambiguous and skipped with a warning.
        """
        login_to_uids = self._get_github_username_map()
        uids_to_logins: dict[str, set[str]] = defaultdict(set)
        for login, uids in login_to_uids.items():
            if len(uids) > 1:
                logger.warning(
                    "Ambiguous GitHub login maps to multiple LDAP uids; skipping",
                    github_login=login,
                    uids=uids,
                )
                continue
            for uid in uids:
                uids_to_logins[uid].add(login)

        resolved: dict[str, str] = {}
        for uid, logins in uids_to_logins.items():
            if len(logins) > 1:
                logger.warning(
                    "Ambiguous LDAP uid claims multiple GitHub logins; skipping",
                    org_username=uid,
                    github_logins=sorted(logins),
                )
                continue
            resolved[uid] = next(iter(logins))
        return resolved

    def _group_members_cache_key(
        self, groups: Iterable[str], *, include_github_usernames: bool
    ) -> str:
        """Generate a deterministic cache key for a set of groups + enrichment flag."""
        sorted_groups = ",".join(sorted(groups))
        key_material = f"{sorted_groups}|{include_github_usernames}"
        group_hash = hashlib.sha256(key_material.encode()).hexdigest()[:16]
        return f"ldap:{self.cache_key_prefix}:groups:members:v2:{group_hash}"

    def _group_dn(self, cn: str) -> str:
        """Build the full DN for a group CN under the FreeIPA groups container."""
        return f"cn={cn},cn=groups,cn=accounts,{self.api.base_dn}"

    def get_group_members(
        self, groups: Iterable[str], *, include_github_usernames: bool = True
    ) -> list[LdapGroupResult]:
        """Resolve members of one or more LDAP groups (cached with distributed locking).

        Fail-closed: raises ValidationError if any group's membership exceeds
        settings.ldap.max_group_size, rather than truncating it - a role
        membership source must never silently lose members.

        Only groups confirmed to exist in LDAP are present in the result; a
        requested group CN that does not exist is omitted entirely, so callers
        can distinguish a confirmed-empty group (present, empty members) from
        an unresolved one (absent from the result) and must not treat the
        latter as empty.

        Args:
            groups: Short group CNs to resolve (e.g. "my-ldap-group")
            include_github_usernames: Whether to enrich each member with its
                GitHub username (resolved via rhatSocialURL)

        Returns:
            List of LdapGroupResult, one per group confirmed to exist

        Raises:
            ValidationError: If any resolved group exceeds max_group_size
        """
        group_list = sorted(set(groups))
        if not group_list:
            return []

        cache_key = self._group_members_cache_key(
            group_list, include_github_usernames=include_github_usernames
        )

        if cached := self.cache.get_obj(cache_key, CachedGroupMembers):
            return cached.groups

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedGroupMembers):
                return cached.groups

            with self.api:
                existing_cns = self.api.check_groups_exist(group_list)
                dn_by_cn = {cn: self._group_dn(cn) for cn in existing_cns}
                ldap_groups = self.api.get_group_members(list(dn_by_cn.values()))

            members_by_cn: dict[str, frozenset[LdapUser]] = {
                cn: frozenset() for cn in existing_cns
            }
            for ldap_group in ldap_groups:
                members_by_cn[ldap_group.cn] = ldap_group.members

            github_by_org_username = (
                self._get_org_username_to_github_map()
                if include_github_usernames
                else {}
            )

            results: list[LdapGroupResult] = []
            for cn in sorted(existing_cns):
                resolved_members: list[LdapGroupMember] = []
                for member in sorted(members_by_cn[cn], key=lambda user: user.username):
                    if not member.name:
                        raise ValidationError(
                            f"LDAP user '{member.username}' has no name"
                        )
                    resolved_members.append(
                        LdapGroupMember(
                            name=member.name,
                            org_username=member.username,
                            github_username=github_by_org_username.get(member.username),
                        )
                    )
                results.append(LdapGroupResult(group=cn, members=resolved_members))

            for result in results:
                if len(result.members) > self.settings.ldap.max_group_size:
                    raise ValidationError(
                        f"LDAP group '{result.group}' has {len(result.members)} "
                        f"members, exceeding the configured max_group_size of "
                        f"{self.settings.ldap.max_group_size}"
                    )

            self.cache.set_obj(
                cache_key,
                CachedGroupMembers(groups=results),
                ttl=self.settings.ldap.groups_cache_ttl,
            )
            return results
