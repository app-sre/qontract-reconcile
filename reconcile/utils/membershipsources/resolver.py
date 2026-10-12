from __future__ import annotations

from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sretoolbox.utils import threaded

from reconcile.utils.grouping import group_by
from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source,
)
from reconcile.utils.membershipsources.ldap_resolver import (
    create_ldap_membership_resolver_sync,
)
from reconcile.utils.membershipsources.models import (
    MembershipProvider,
    MembershipProviderSource,
    ProviderMember,
    ProviderResolver,
    RoleWithMemberships,
    resolve_role,
)

if TYPE_CHECKING:
    from collections.abc import (
        Iterable,
        Mapping,
        Sequence,
    )

    from reconcile.utils.membershipsources.ldap_resolver import LdapSettings


@dataclass
class GroupResolverJob:
    provider: MembershipProvider
    groups: set[str]


def build_resolver_jobs(
    roles: Sequence[RoleWithMemberships],
) -> list[GroupResolverJob]:
    """
    Bundles groups to be resolve by provider so that they can be resolved
    in batches.
    """
    groups = group_by(
        (ms for r in roles for ms in r.member_sources or []),
        key=lambda ms: ms.provider.name,
    )
    return [
        GroupResolverJob(
            provider=g[0].provider,
            groups={ms.group for ms in g},
        )
        for g in groups.values()
    ]


ProviderGroup = tuple[str, str]


def get_resolver_for_provider_source(
    source: MembershipProviderSource,
    resolvers: Mapping[str, ProviderResolver],
) -> ProviderResolver:
    """Dispatch on the `provider` discriminator string.

    `resolvers` is built by resolve_role_members() with any
    dependency-injected values (e.g. LDAP settings/secret manager URL)
    already bound into the registered closures - this function never
    fetches settings/secrets itself, and never imports or matches against
    a concrete class from reconcile/gql_definitions.
    """
    resolver = resolvers.get(source.provider)
    if resolver is None:
        raise ValueError(
            "No resolver available for membership provider source",
            source.provider,
        )
    return resolver


def resolve_groups(
    job: GroupResolverJob,
    resolvers: Mapping[str, ProviderResolver],
) -> dict[ProviderGroup, list[ProviderMember]]:
    """
    Resolves groups and returns a dict with group name as key and a list
    of members as value.
    """
    resolver = get_resolver_for_provider_source(job.provider.source, resolvers)
    return resolver(job.provider.name, job.provider.source, job.groups)


def resolve_role_members[U: BaseModel](
    roles: Sequence[RoleWithMemberships],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    thread_pool: int = 5,
) -> dict[str, list[U]]:
    """
    Resolves members of roles, combining local members and the ones from
    membership sources, as instances of the caller-supplied user_cls.

    Deduplicates by org_username per role - explicit users/bots are added
    first and win over a memberSources-resolved member with the same
    org_username, since they carry richer, integration-specific data.

    Provider registration is dependency-injected: passing ldap_settings and
    secret_manager_url registers the LDAP provider with those values bound
    into its resolver closure, mirroring
    async_resolver.resolve_role_members. Neither this function
    nor the LDAP resolver fetch settings/secrets from global state
    themselves - a caller that needs LDAP support must fetch them and pass
    them in explicitly.

    Raises:
        ValueError: If a role references a provider source with no
            registered resolver (e.g. ldap_settings was not passed but a
            role has an LDAP memberSources entry).
    """
    resolvers: dict[str, ProviderResolver] = {
        "app-interface": resolve_app_interface_membership_source,
    }
    if ldap_settings is not None:
        if secret_manager_url is None:
            raise ValueError(
                "secret_manager_url is required when ldap_settings is provided"
            )
        resolvers["ldap"] = create_ldap_membership_resolver_sync(
            ldap_settings, secret_manager_url
        )

    resolver_jobs = build_resolver_jobs(roles)
    processed_jobs: Iterable[dict[ProviderGroup, list[ProviderMember]]] = threaded.run(
        func=resolve_groups,
        iterable=resolver_jobs,
        thread_pool_size=thread_pool,
        resolvers=resolvers,
    )
    resolved_groups: dict[ProviderGroup, list[ProviderMember]] = dict(
        chain.from_iterable(d.items() for d in processed_jobs)
    )

    return {r.name: resolve_role(r, user_cls, resolved_groups) for r in roles}
