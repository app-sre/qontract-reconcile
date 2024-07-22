import base64
from collections.abc import Generator
from contextlib import contextmanager

from reconcile import queries
from reconcile.gql_definitions.fragments.membership_source import (
    AppInterfaceMembershipProviderSourceV1,
)
from reconcile.gql_definitions.membershipsources.roles import RoleV1
from reconcile.gql_definitions.membershipsources.roles import (
    query as mebershipsource_query,
)
from reconcile.utils import gql
from reconcile.utils.membershipsources.models import (
    ProviderGroup,
    RoleBot,
    RoleMember,
    RoleUser,
)
from reconcile.utils.secret_reader import SecretReader


@contextmanager
def gql_api_for_source(
    source: AppInterfaceMembershipProviderSourceV1,
) -> Generator[gql.GqlApi, None, None]:
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
    source: AppInterfaceMembershipProviderSourceV1,
    groups: set[str],
) -> dict[ProviderGroup, list[RoleMember]]:
    with gql_api_for_source(source) as gql_api:
        roles = (
            mebershipsource_query(
                gql_api.query, variables={"filter": {"name": {"in": list(groups)}}}
            ).roles
            or []
        )
        return {(provider_name, r.name): build_member_list(r) for r in roles}


def build_member_list(role: RoleV1) -> list[RoleMember]:
    members: list[RoleMember] = []
    members.extend([RoleUser(**u.dict()) for u in role.users or []])
    members.extend([RoleBot(**b.dict()) for b in role.bots or [] if b.org_username])
    return members
