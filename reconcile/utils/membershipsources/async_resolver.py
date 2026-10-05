from __future__ import annotations

import asyncio
from itertools import chain
from typing import TYPE_CHECKING

from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source_async,
)
from reconcile.utils.membershipsources.ldap_resolver import (
    create_ldap_membership_resolver,
)
from reconcile.utils.membershipsources.models import resolve_role
from reconcile.utils.membershipsources.resolver import build_resolver_jobs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import BaseModel

    from reconcile.utils.membershipsources.ldap_resolver import LdapSettings
    from reconcile.utils.membershipsources.models import (
        AsyncProviderResolver,
        ProviderGroup,
        ProviderMember,
        RoleWithMemberships,
    )
    from reconcile.utils.membershipsources.resolver import GroupResolverJob


async def _resolve_job(
    job: GroupResolverJob,
    resolvers: Mapping[str, AsyncProviderResolver],
) -> dict[ProviderGroup, list[ProviderMember]]:
    """Dispatch on the `provider` discriminator string.

    Never imports or matches against a concrete class from
    reconcile/gql_definitions - see resolver.get_resolver_for_provider_source
    for the equivalent sync-path dispatch.
    """
    resolver = resolvers.get(job.provider.source.provider)
    if resolver is None:
        raise ValueError(
            "No async resolver registered for membership provider source",
            job.provider.source.provider,
        )
    return await resolver(job.provider.name, job.provider.source, job.groups)


async def resolve_role_members[U: BaseModel](
    roles: Sequence[RoleWithMemberships],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
) -> dict[str, list[U]]:
    """Async counterpart of resolver.resolve_role_members.

    Resolves every role's members, from every source, as instances of the
    caller-supplied user_cls, in one call, regardless of source.
    Deduplicates by org_username per role - explicit users are added first
    and win over a memberSources-resolved member with the same
    org_username, since they carry richer, integration-specific data.

    Feature parity with the sync resolve_role_members: the app-interface
    provider is always available (it needs no injected dependencies - see
    resolve_app_interface_membership_source), while LDAP is registered only
    when ldap_settings and secret_manager_url are passed. Future providers
    follow the same pattern (an optional kwarg that, when set, registers
    itself).

    Raises:
        ValueError: If a role references a provider source with no
            registered resolver (e.g. ldap_settings was not passed but a
            role has an LDAP memberSources entry).
    """
    resolvers: dict[str, AsyncProviderResolver] = {
        "app-interface": resolve_app_interface_membership_source_async,
    }
    if ldap_settings is not None:
        if secret_manager_url is None:
            raise ValueError(
                "secret_manager_url is required when ldap_settings is provided"
            )
        resolvers["ldap"] = create_ldap_membership_resolver(
            ldap_settings, secret_manager_url
        )

    resolved_groups: dict[ProviderGroup, list[ProviderMember]] = {}
    if jobs := build_resolver_jobs(roles):
        job_results = await asyncio.gather(*[
            _resolve_job(job, resolvers) for job in jobs
        ])
        resolved_groups = dict(chain.from_iterable(r.items() for r in job_results))

    return {role.name: resolve_role(role, user_cls, resolved_groups) for role in roles}
