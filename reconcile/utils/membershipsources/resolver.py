from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING, overload

from pydantic import BaseModel
from qontract_api_client.client import client as qontract_api_client
from sretoolbox.utils import threaded

from reconcile.utils.grouping import group_by
from reconcile.utils.membershipsources import async_resolver
from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source,
)
from reconcile.utils.membershipsources.models import (
    GithubIdentity,
    MembershipProvider,
    MembershipProviderSource,
    ProviderMember,
    ProviderResolver,
    RoleMembershipFields,
    has_ldap_sources,
    resolve_role,
)
from reconcile.utils.runtime.integration import setup_qontract_api_client

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Iterable,
        Mapping,
        Sequence,
    )

    from reconcile.utils.membershipsources.ldap_resolver import LdapSettings


def has_github_username(member: ProviderMember) -> bool:
    """Exclude members without GitHub identities before validating GitHub users."""
    return isinstance(member, GithubIdentity) and bool(member.github_username)


@dataclass
class GroupResolverJob:
    provider: MembershipProvider
    groups: set[str]


def build_resolver_jobs(
    roles: Sequence[RoleMembershipFields],
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


@overload
def resolve_role_members[R: RoleMembershipFields, U: BaseModel](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    thread_pool: int = 5,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: None = None,
) -> list[R]: ...


@overload
def resolve_role_members[
    R: RoleMembershipFields,
    U: BaseModel,
    T: RoleMembershipFields,
](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    thread_pool: int = 5,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: type[T],
) -> list[T]: ...


@overload
def resolve_role_members[
    R: RoleMembershipFields,
    U: BaseModel,
    T: RoleMembershipFields,
](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    thread_pool: int = 5,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: type[T] | None,
) -> list[R | T]: ...


def resolve_role_members[
    R: RoleMembershipFields,
    U: BaseModel,
    T: RoleMembershipFields,
](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    thread_pool: int = 5,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: type[T] | None = None,
) -> list[R] | list[T] | list[R | T]:
    """
    Resolves members of roles, combining local members and the ones from
    membership sources, as instances of the caller-supplied user_cls.

    Deduplicates by org_username per role - valid explicit users are added
    first and win over a memberSources-resolved member with the same
    org_username, since they carry richer, integration-specific data.

    LDAP dependencies can be injected. When omitted for LDAP-backed roles,
    the async resolver loads settings using query_func and the configured Vault
    URL. LDAP jobs share one event loop, and HTTP clients are closed before it
    exits. Explicit/app-interface-only roles need no LDAP or API configuration.

    Raises:
        ValueError: If injected LDAP settings lack a secret manager URL or a
            role references an unsupported provider.
    """
    if ldap_settings is not None and secret_manager_url is None:
        raise ValueError(
            "secret_manager_url is required when ldap_settings is provided"
        )

    if has_ldap_sources(roles):
        if ldap_settings is None:
            setup_qontract_api_client()

        async def resolve_and_close() -> list[R | T]:
            try:
                return await async_resolver.resolve_role_members(
                    roles,
                    user_cls=user_cls,
                    ldap_settings=ldap_settings,
                    secret_manager_url=secret_manager_url,
                    member_filter=member_filter,
                    query_func=query_func,
                    role_cls=role_cls,
                )
            finally:
                await qontract_api_client.aclose()

        return asyncio.run(resolve_and_close())

    resolvers: dict[str, ProviderResolver] = {
        "app-interface": resolve_app_interface_membership_source
    }

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

    return [
        resolve_role(
            r, user_cls, resolved_groups, member_filter=member_filter, role_cls=role_cls
        )
        for r in roles
    ]
