from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from reconcile import queries
from reconcile.gql_definitions.membershipsources.roles import RoleV1
from reconcile.gql_definitions.membershipsources.roles import (
    query as mebershipsource_query,
)
from reconcile.utils import gql
from reconcile.utils.secret_reader import HasSecret, SecretReader

if TYPE_CHECKING:
    from collections.abc import Generator

    from reconcile.utils.membershipsources.models import ProviderGroup, ProviderMember


class AppInterfaceProviderSource(Protocol):
    """Structural shape needed to reach a remote app-interface instance.

    Satisfied by the real AppInterfaceMembershipProviderSourceV1 (and by
    anything else with this shape) without importing it.
    """

    @property
    def url(self) -> str: ...

    @property
    def username(self) -> HasSecret: ...

    @property
    def password(self) -> HasSecret: ...


@contextmanager
def gql_api_for_source(
    source: AppInterfaceProviderSource,
) -> Generator[gql.GqlApi]:
    settings = queries.get_secret_reader_settings()
    secret_reader = SecretReader(settings=settings)
    username = secret_reader.read_secret(source.username)
    password = secret_reader.read_secret(source.password)
    basic_auth_info = base64.b64encode(f"{username}:{password}".encode()).decode()
    gql_api = gql.get_api_for_server(
        source.url, f"Basic {basic_auth_info}", None, False
    )
    try:
        yield gql_api
    finally:
        gql_api.close()


def resolve_app_interface_membership_source(
    provider_name: str,
    source: AppInterfaceProviderSource,
    groups: set[str],
) -> dict[ProviderGroup, list[ProviderMember]]:
    with gql_api_for_source(source) as gql_api:
        roles = (
            mebershipsource_query(
                gql_api.query, variables={"filter": {"name": {"in": list(groups)}}}
            ).roles
            or []
        )
        resolved: dict[ProviderGroup, list[ProviderMember]] = {
            (provider_name, r.name): build_member_list(r) for r in roles
        }
        # A requested role name absent from the response means it doesn't
        # exist on the remote instance (renamed/removed) - distinct from a
        # role that exists with no users/bots. Treating the omission as
        # empty would silently remove real members from whatever
        # role/usergroup depends on it - fail closed instead, matching the
        # LDAP resolver's "unresolved != empty" handling.
        if missing := groups - {g for _, g in resolved}:
            raise RuntimeError(
                f"App-interface roles could not be resolved: {sorted(missing)}"
            )
        return resolved


async def resolve_app_interface_membership_source_async(
    provider_name: str,
    source: AppInterfaceProviderSource,
    groups: set[str],
) -> dict[ProviderGroup, list[ProviderMember]]:
    """Async wrapper for async_resolver.resolve_role_members, so the app-interface
    provider is available on both the sync and async paths - the same
    feature set, not just LDAP.

    The underlying GQL client call is synchronous/blocking; running it in
    a thread keeps it off the event loop without duplicating the query
    logic.
    """
    return await asyncio.to_thread(
        resolve_app_interface_membership_source, provider_name, source, groups
    )


def build_member_list(role: RoleV1) -> list[ProviderMember]:
    """Return the role's users/bots as-is; they already satisfy ProviderMember.

    The resolver framework converts each one to the caller-supplied user_cls -
    this function must not narrow their attributes to any particular shape.
    """
    members: list[ProviderMember] = list(role.users or [])
    members.extend(b for b in role.bots or [] if b.org_username)
    return members
