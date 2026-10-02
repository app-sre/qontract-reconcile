from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from qontract_api_client.client import ldap_group_members
from qontract_api_client.schemas import LdapDirectSecret, LdapGroupMembersRequest

if TYPE_CHECKING:
    from reconcile.utils.membershipsources.models import (
        AsyncProviderResolver,
        MembershipProviderSource,
        ProviderGroup,
        ProviderMember,
        ProviderResolver,
    )
    from reconcile.utils.secret_reader import HasSecret


class LdapSettings(Protocol):
    """Structural shape of the app-interface LDAP settings needed to reach
    the external LDAP endpoint.

    Satisfied by the real LdapSettingsV1 (reconcile.gql_definitions.common.
    ldap_settings) without importing it - reconcile/utils must not depend
    on a concrete class from reconcile/gql_definitions.
    """

    @property
    def server_url(self) -> str: ...

    @property
    def base_dn(self) -> str: ...

    @property
    def credentials(self) -> HasSecret | None: ...


def create_ldap_membership_resolver(
    ldap_settings: LdapSettings,
    secret_manager_url: str,
) -> AsyncProviderResolver:
    """Create an async LDAP membership source resolver.

    Returns a closure that calls POST /external/ldap/groups/members and
    returns the raw LdapGroupMember instances - async_resolver.resolve_role_members
    converts them to the caller's user_cls.

    The credentials check is deferred to the closure itself (not performed
    here) so that callers who always pass ldap_settings (e.g. every
    slack-usergroups-api permission) don't fail when no role actually has
    an LDAP memberSources entry to resolve.
    """

    async def resolve(
        provider_name: str,
        source: MembershipProviderSource,
        groups: set[str],
    ) -> dict[ProviderGroup, list[ProviderMember]]:
        if not ldap_settings.credentials:
            raise RuntimeError("LDAP credentials not found in settings")

        response = await ldap_group_members(
            LdapGroupMembersRequest(
                groups=sorted(groups),
                secret=LdapDirectSecret(
                    secret_manager_url=secret_manager_url,
                    path=ldap_settings.credentials.path,
                    field=ldap_settings.credentials.field,
                    version=ldap_settings.credentials.version,
                    server_url=ldap_settings.server_url,
                    base_dn=ldap_settings.base_dn,
                ),
            )
        )
        # LDAP CN matching is case-insensitive, so the endpoint can return a
        # group's stored spelling (e.g. "team-a") even when the caller
        # requested a different casing (e.g. "Team-A", as configured in
        # app-interface). resolve_role() looks members up by the requested
        # spelling, so the result key must use that spelling too - otherwise
        # a genuinely resolved group would look both missing (triggering the
        # fail-closed check below) and empty to the caller.
        requested_by_lower = {g.lower(): g for g in groups}
        resolved: dict[ProviderGroup, list[ProviderMember]] = {
            (
                provider_name,
                requested_by_lower.get(group.group.lower(), group.group),
            ): list(group.members or [])
            for group in response.groups
        }
        # The endpoint omits a group entirely when it doesn't exist in LDAP,
        # distinct from a confirmed-empty group (present with members=[]).
        # Treating an omission the same as empty would silently remove real
        # members from whatever role/usergroup depends on this group - fail
        # closed instead, matching the design's "unresolved != empty"
        # requirement.
        if missing := groups - {g for _, g in resolved}:
            raise RuntimeError(f"LDAP groups could not be resolved: {sorted(missing)}")
        return resolved

    return resolve


def create_ldap_membership_resolver_sync(
    ldap_settings: LdapSettings,
    secret_manager_url: str,
) -> ProviderResolver:
    """Create a sync LDAP membership source resolver for threaded.run-based
    callers (change_owners etc.).

    Dependency-injected, like create_ldap_membership_resolver: ldap_settings
    and secret_manager_url are supplied by the caller (resolve_role_members)
    rather than fetched from global state here. Wraps the async resolver via
    asyncio.run() - safe because threaded.run() runs each resolver call in
    its own thread.
    """
    async_resolve = create_ldap_membership_resolver(ldap_settings, secret_manager_url)

    def resolve(
        provider_name: str,
        source: MembershipProviderSource,
        groups: set[str],
    ) -> dict[ProviderGroup, list[ProviderMember]]:
        return asyncio.run(async_resolve(provider_name, source, groups))

    return resolve
