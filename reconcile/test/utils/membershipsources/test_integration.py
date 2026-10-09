from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx2
import pytest
from clientele.http.httpx_backend import HttpxHTTPBackend
from qontract_api_client.client import client as qontract_api_client
from qontract_api_client.config import Config
from qontract_api_client.schemas import (
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapGroupResult,
)

from reconcile.test.utils.membershipsources.fixtures import (
    CustomRole,
    build_ldap_membership_source,
    build_role,
)
from reconcile.test.utils.membershipsources.test_resolver import Member
from reconcile.utils.membershipsources.models import resolve_role

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture


def test_resolve_role_rejects_missing_group() -> None:
    role = build_role(
        name="team",
        member_sources=[build_ldap_membership_source(name="ldap", group="team")],
    )
    with pytest.raises(ValueError, match="team"):
        resolve_role(role, Member, {}, role_cls=CustomRole[Member])


@pytest.mark.parametrize("github_username", [None, "alice-gh"])
def test_resolve_role_skips_users_rejected_by_generated_model(
    github_username: str | None,
) -> None:
    from reconcile.gql_definitions.github_owners_api.roles import UserV1

    role = build_role(
        name="team",
        member_sources=[build_ldap_membership_source(name="ldap", group="team")],
    )
    resolved = resolve_role(
        role,
        UserV1,
        {
            ("ldap", "team"): [
                LdapGroupMember(
                    name="Alice", org_username="alice", github_username=github_username
                )
            ]
        },
        role_cls=CustomRole[UserV1],
    )
    expected = (
        []
        if github_username is None
        else [UserV1(org_username="alice", github_username=github_username)]
    )
    assert resolved.users == expected


def test_skipped_user_does_not_block_valid_duplicate() -> None:
    from reconcile.gql_definitions.github_owners_api.roles import UserV1

    role = build_role(
        name="team",
        member_sources=[build_ldap_membership_source(name="ldap", group="team")],
    )
    resolved = resolve_role(
        role,
        UserV1,
        {
            ("ldap", "team"): [
                LdapGroupMember(
                    name="Alice", org_username="alice", github_username=None
                ),
                LdapGroupMember(
                    name="Alice", org_username="alice", github_username="alice-gh"
                ),
            ]
        },
        role_cls=CustomRole[UserV1],
    )
    assert resolved.users == [UserV1(org_username="alice", github_username="alice-gh")]


def test_required_nullable_alias_is_supplied_as_none() -> None:
    from pydantic import BaseModel, Field

    class UserWithExpiry(BaseModel, frozen=True, extra="forbid"):
        org_username: str
        expiration_date: str | None = Field(..., alias="expirationDate")

    resolved = resolve_role(
        build_role(name="team", users=["alice"]),
        UserWithExpiry,
        {},
        role_cls=CustomRole[UserWithExpiry],
    )
    assert resolved.users == [UserWithExpiry(org_username="alice", expirationDate=None)]


def test_sync_resolver_returns_roles_with_separate_users_and_bots() -> None:
    from reconcile.utils.membershipsources.resolver import resolve_role_members

    role = build_role(name="team", users=["alice"], bots=["bot"])
    resolved = resolve_role_members(
        [role], user_cls=Member, role_cls=CustomRole[Member]
    )
    assert isinstance(resolved, list)
    assert resolved[0].name == role.name
    assert resolved[0].users == [Member(name="alice", org_username="alice")]
    assert resolved[0].bots == role.bots
    assert [user.org_username for user in role.users] == ["alice"]


@pytest.mark.asyncio
async def test_async_resolver_returns_roles_with_separate_users_and_bots() -> None:
    from reconcile.utils.membershipsources.async_resolver import resolve_role_members

    role = build_role(name="team", users=["alice"], bots=["bot"])
    resolved = await resolve_role_members(
        [role], user_cls=Member, role_cls=CustomRole[Member]
    )
    assert isinstance(resolved, list)
    assert resolved[0].name == role.name
    assert resolved[0].users == [Member(name="alice", org_username="alice")]
    assert resolved[0].bots == role.bots


def test_resolve_role_projects_provider_fields_into_generated_users() -> None:
    from reconcile.gql_definitions.automated_actions.instance import UserV1

    role = build_role(name="team", users=["alice"])
    assert resolve_role(role, UserV1, {}, role_cls=CustomRole[UserV1]).users == [
        UserV1(org_username="alice")
    ]


def test_resolve_role_supplies_absent_nullable_generated_fields() -> None:
    from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
        UserV1,
    )

    role = build_role(name="team", users=["alice"], bots=["bot"])
    members = resolve_role(role, UserV1, {}, role_cls=CustomRole[UserV1])
    assert members.users[0] == UserV1(
        name="alice", org_username="alice", tag_on_merge_requests=None
    )


def test_resolve_role_does_not_fabricate_required_fields(
    gql_class_factory: Callable,
) -> None:
    from reconcile.gql_definitions.automated_actions.instance import RoleV1
    from reconcile.gql_definitions.glitchtip.glitchtip_project import UserV1

    role = gql_class_factory(
        RoleV1, {"name": "team", "users": [{"org_username": "alice"}]}
    )
    assert resolve_role(role, UserV1, {}).users == []


def test_resolve_role_accepts_generated_role_without_bots(
    gql_class_factory: Callable,
) -> None:
    from reconcile.gql_definitions.sendgrid_teammates.roles import RoleV1, UserV1

    role = gql_class_factory(
        RoleV1, {"name": "team", "users": [{"org_username": "alice"}]}
    )
    assert resolve_role(role, UserV1, {}).users == [UserV1(org_username="alice")]


def test_role_contract_declares_optional_bots() -> None:
    from collections.abc import Sequence
    from inspect import getattr_static
    from typing import get_type_hints

    from pydantic import BaseModel

    from reconcile.utils.membershipsources.models import RoleWithMemberships

    bots = getattr_static(RoleWithMemberships, "bots")
    assert isinstance(bots, property)
    assert bots.fget is not None
    assert get_type_hints(bots.fget)["return"] == Sequence[BaseModel] | None


def test_role_protocol_validation_parameter_matches_pydantic() -> None:
    from inspect import signature

    from pydantic import BaseModel

    from reconcile.utils.membershipsources.models import RoleMembershipFields

    assert next(
        iter(signature(RoleMembershipFields.model_validate).parameters)
    ) == next(iter(signature(BaseModel.model_validate).parameters))


def test_original_gql_role_type_and_bots_are_preserved(
    gql_class_factory: Callable,
) -> None:
    from reconcile.gql_definitions.gitlab_members.permissions import RoleV1, UserV1

    role = gql_class_factory(
        RoleV1,
        {
            "name": "team",
            "users": [{"org_username": "explicit"}],
            "bots": [{"org_username": "bot"}],
        },
    )
    role.member_sources = [build_ldap_membership_source(name="ldap", group="team")]
    before = role.model_dump()
    resolved = resolve_role(
        role,
        UserV1,
        {("ldap", "team"): [LdapGroupMember(name="Alice", org_username="alice")]},
    )
    assert type(resolved) is RoleV1
    assert [user.org_username for user in resolved.users] == ["explicit", "alice"]
    assert resolved.bots == role.bots
    assert role.model_dump() == before


@pytest.mark.asyncio
async def test_public_resolvers_return_original_gql_roles(
    gql_class_factory: Callable,
) -> None:
    from reconcile.gql_definitions.gitlab_members.permissions import RoleV1, UserV1
    from reconcile.utils.membershipsources import async_resolver, resolver

    role = gql_class_factory(
        RoleV1,
        {
            "name": "team",
            "users": [{"org_username": "alice"}],
            "bots": [{"org_username": "bot"}],
        },
    )
    for result in (
        resolver.resolve_role_members([role], user_cls=UserV1),
        await async_resolver.resolve_role_members([role], user_cls=UserV1),
    ):
        assert isinstance(result, list)
        assert type(result[0]) is RoleV1
        assert result[0].bots == role.bots
        assert result[0].users == role.users


def test_resolve_role_ignores_bots_without_org_username(
    gql_class_factory: Callable,
) -> None:
    from reconcile.gql_definitions.common.app_interface_roles import RoleV1
    from reconcile.openshift_bindings.models import BindingUser as GithubUser
    from reconcile.openshift_bindings.models import RoleBindingRole

    role = gql_class_factory(
        RoleV1,
        {
            "name": "team",
            "users": [{"org_username": "alice", "github_username": "AliceGH"}],
            "bots": [{"openshift_serviceaccount": "ns/bot"}],
        },
    )
    assert resolve_role(role, GithubUser, {}, role_cls=RoleBindingRole).users == [
        GithubUser(org_username="alice", github_username="AliceGH")
    ]


def test_sync_resolver_accepts_comparison_bundle_query(mocker: MockerFixture) -> None:
    from reconcile.utils.membershipsources.resolver import resolve_role_members

    query_func = mocker.Mock(
        side_effect=AssertionError("Explicit roles need no settings query")
    )
    result = resolve_role_members(
        [build_role(name="team", users=["alice"])],
        user_cls=Member,
        query_func=query_func,
        role_cls=CustomRole[Member],
    )
    assert result[0].users == [Member(name="alice", org_username="alice")]
    query_func.assert_not_called()


@pytest.mark.asyncio
async def test_async_resolver_accepts_comparison_bundle_query(
    mocker: MockerFixture,
) -> None:
    from reconcile.utils.membershipsources.async_resolver import resolve_role_members

    query_func = mocker.Mock(
        side_effect=AssertionError("Explicit roles need no settings query")
    )
    result = await resolve_role_members(
        [build_role(name="team", users=["alice"])],
        user_cls=Member,
        query_func=query_func,
        role_cls=CustomRole[Member],
    )
    assert result[0].users == [Member(name="alice", org_username="alice")]
    query_func.assert_not_called()


def test_sync_integration_resolution_repeated_calls(mocker: MockerFixture) -> None:
    from reconcile.utils.membershipsources.resolver import resolve_role_members

    settings = mocker.Mock()
    settings.credentials.path = "ldap/creds"
    settings.credentials.field = "password"
    settings.credentials.version = None
    settings.server_url = "ldaps://ldap.example.com"
    settings.base_dn = "dc=example,dc=com"
    mocker.patch(
        "reconcile.utils.membershipsources.async_resolver.get_ldap_settings",
        return_value=settings,
    )
    mocker.patch(
        "reconcile.utils.membershipsources.async_resolver.get_config",
        return_value={"vault": {"server": "https://vault.example.com"}},
    )
    setup = mocker.patch(
        "reconcile.utils.membershipsources.resolver.setup_qontract_api_client"
    )
    close = mocker.patch(
        "reconcile.utils.membershipsources.resolver.qontract_api_client.aclose",
        new_callable=mocker.AsyncMock,
    )
    endpoint = mocker.patch(
        "reconcile.utils.membershipsources.ldap_resolver.ldap_group_members",
        new_callable=mocker.AsyncMock,
        return_value=LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team",
                    members=[
                        LdapGroupMember(
                            name="alice", org_username="alice", github_username=None
                        )
                    ],
                )
            ]
        ),
    )
    roles = [
        build_role(
            name="team",
            member_sources=[build_ldap_membership_source(name="ldap", group="team")],
        )
    ]

    for _ in range(2):
        assert resolve_role_members(
            roles, user_cls=Member, role_cls=CustomRole[Member]
        )[0].users == [Member(name="alice", org_username="alice")]
    assert endpoint.await_count == 2
    assert close.await_count == 2
    assert setup.call_count == 2


def test_explicit_members_do_not_require_ldap_configuration(
    mocker: MockerFixture,
) -> None:
    from reconcile.utils.membershipsources.resolver import resolve_role_members

    settings = mocker.patch(
        "reconcile.utils.membershipsources.async_resolver.get_ldap_settings",
        side_effect=AssertionError("unnecessary LDAP configuration"),
    )
    config = mocker.patch(
        "reconcile.utils.membershipsources.async_resolver.get_config",
        side_effect=AssertionError("unnecessary API configuration"),
    )
    result = resolve_role_members(
        [build_role(name="team", users=["alice"])],
        user_cls=Member,
        role_cls=CustomRole[Member],
    )
    assert result[0].users == [Member(name="alice", org_username="alice")]
    settings.assert_not_called()
    config.assert_not_called()


def test_generated_client_is_closed_before_reusing_a_new_event_loop(
    mocker: MockerFixture,
) -> None:
    from reconcile.utils.membershipsources.resolver import resolve_role_members

    loops = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        loops.append(asyncio.get_running_loop())
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx2.Response(
            200,
            json=LdapGroupMembersResponse(
                groups=[
                    LdapGroupResult(
                        group="team",
                        members=[
                            LdapGroupMember(
                                name="alice", org_username="alice", github_username=None
                            )
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )

    backend = HttpxHTTPBackend(
        client_options={
            "base_url": "https://api.example.com",
            "transport": httpx2.MockTransport(handle),
        }
    )
    mocker.patch.object(
        qontract_api_client,
        "config",
        Config(http_backend=backend, headers={"Authorization": "Bearer test-token"}),
    )
    mocker.patch("reconcile.utils.membershipsources.resolver.setup_qontract_api_client")
    mocker.patch(
        "reconcile.utils.membershipsources.async_resolver.get_config",
        return_value={"vault": {"server": "https://vault.example.com"}},
    )
    settings = mocker.Mock()
    settings.credentials.path = "ldap/creds"
    settings.credentials.field = "password"
    settings.credentials.version = None
    settings.server_url = "ldaps://ldap.example.com"
    settings.base_dn = "dc=example,dc=com"
    mocker.patch(
        "reconcile.utils.membershipsources.async_resolver.get_ldap_settings",
        return_value=settings,
    )
    roles = [
        build_role(
            name="team",
            member_sources=[build_ldap_membership_source(name="ldap", group="team")],
        )
    ]
    for _ in range(2):
        assert resolve_role_members(
            roles, user_cls=Member, role_cls=CustomRole[Member]
        )[0].users == [Member(name="alice", org_username="alice")]
    assert len(loops) == 2
    assert loops[0] is not loops[1]
    assert all(loop.is_closed() for loop in loops)


def test_sync_resolution_failure_closes_client(mocker: MockerFixture) -> None:
    from reconcile.utils.membershipsources.resolver import resolve_role_members

    mocker.patch("reconcile.utils.membershipsources.resolver.setup_qontract_api_client")
    mocker.patch(
        "reconcile.utils.membershipsources.async_resolver.resolve_role_members",
        new_callable=mocker.AsyncMock,
        side_effect=RuntimeError("resolution failed"),
    )
    close = mocker.patch(
        "reconcile.utils.membershipsources.resolver.qontract_api_client.aclose",
        new_callable=mocker.AsyncMock,
    )
    roles = [
        build_role(
            name="team",
            member_sources=[build_ldap_membership_source(name="ldap", group="team")],
        )
    ]
    with pytest.raises(RuntimeError, match="resolution failed"):
        resolve_role_members(roles, user_cls=Member)
    close.assert_awaited_once()
