from __future__ import annotations

import asyncio
from itertools import chain
from typing import TYPE_CHECKING, overload

from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.utils.config import get_config
from reconcile.utils.membershipsources import resolver
from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source_async,
)
from reconcile.utils.membershipsources.ldap_resolver import (
    create_ldap_membership_resolver,
)
from reconcile.utils.membershipsources.models import (
    has_ldap_sources,
    resolve_role,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from pydantic import BaseModel

    from reconcile.utils.membershipsources.ldap_resolver import LdapSettings
    from reconcile.utils.membershipsources.models import (
        AsyncProviderResolver,
        ProviderGroup,
        ProviderMember,
        RoleMembershipFields,
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


@overload
async def resolve_role_members[R: RoleMembershipFields, U: BaseModel](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: None = None,
) -> list[R]: ...


@overload
async def resolve_role_members[
    R: RoleMembershipFields,
    U: BaseModel,
    T: RoleMembershipFields,
](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: type[T],
) -> list[T]: ...


@overload
async def resolve_role_members[
    R: RoleMembershipFields,
    U: BaseModel,
    T: RoleMembershipFields,
](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: type[T] | None,
) -> list[R | T]: ...


async def resolve_role_members[
    R: RoleMembershipFields,
    U: BaseModel,
    T: RoleMembershipFields,
](
    roles: Sequence[R],
    user_cls: type[U],
    *,
    ldap_settings: LdapSettings | None = None,
    secret_manager_url: str | None = None,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    query_func: Callable | None = None,
    role_cls: type[T] | None = None,
) -> list[R] | list[T] | list[R | T]:
    """Async counterpart of resolver.resolve_role_members.

    Resolves every role's members, from every source, as instances of the
    caller-supplied user_cls, in one call, regardless of source.
    Deduplicates by org_username per role - explicit users are added first
    and win over a memberSources-resolved member with the same
    org_username, since they carry richer, integration-specific data.

    The app-interface provider is always available. LDAP settings and the Vault
    URL are loaded only for LDAP-backed roles, unless supplied by the caller.
    query_func preserves comparison-bundle configuration for authorization.
    Client lifecycle belongs to the existing async integration runner; the sync
    entry point closes clients before its event loop exits.

    Raises:
        ValueError: If injected LDAP settings lack a secret manager URL or a
            role references an unsupported provider.
    """
    if ldap_settings is None and has_ldap_sources(roles):
        ldap_settings = get_ldap_settings(query_func=query_func)
        if secret_manager_url is None:
            secret_manager_url = get_config()["vault"]["server"]

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
    if jobs := resolver.build_resolver_jobs(roles):
        job_results = await asyncio.gather(*[
            _resolve_job(job, resolvers) for job in jobs
        ])
        resolved_groups = dict(chain.from_iterable(r.items() for r in job_results))

    return [
        resolve_role(
            role,
            user_cls,
            resolved_groups,
            member_filter=member_filter,
            role_cls=role_cls,
        )
        for role in roles
    ]
