from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel
from qontract_api_client.schemas import (
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapGroupResult,
)

from reconcile.gql_definitions.common.ldap_settings import LdapSettingsV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.test.utils.membershipsources.fixtures import (
    build_app_interface_membership_source,
    build_ldap_membership_source,
    build_role,
)
from reconcile.utils.membershipsources import async_resolver
from reconcile.utils.membershipsources.async_resolver import resolve_role_members

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from reconcile.gql_definitions.fragments.membership_source import (
        AppInterfaceMembershipProviderSourceV1,
    )
    from reconcile.utils.membershipsources.models import Bot, User

_MOD = "reconcile.utils.membershipsources.ldap_resolver"


class Member(BaseModel, extra="ignore"):
    org_username: str
    gov_slack_email_local_part: str | None = None


def _ldap_settings() -> LdapSettingsV1:
    return LdapSettingsV1(
        serverUrl="ldap://freeipa.example.com",
        baseDn="dc=example,dc=com",
        credentials=VaultSecret(
            path="secret/ldap/bind",
            field="password",
            version=None,
            format=None,
            url=None,
        ),
    )


@pytest.mark.asyncio
async def test_resolve_role_members_no_sources_returns_explicit_only() -> None:
    """No memberSources on any role: no provider resolution happens at all."""
    roles = [build_role(name="role1", users=["alice"], bots=["bot1"])]

    result = await resolve_role_members(roles, user_cls=Member)

    assert {m.org_username for m in result["role1"]} == {"alice", "bot1"}


@pytest.mark.asyncio
async def test_resolve_role_members_ldap_settings_without_secret_manager_url_raises() -> (
    None
):
    roles = [build_role(name="role1", users=["alice"])]

    with pytest.raises(ValueError, match="secret_manager_url is required"):
        await resolve_role_members(
            roles, user_cls=Member, ldap_settings=_ldap_settings()
        )


@pytest.mark.asyncio
async def test_resolve_role_members_ldap_settings_unused_does_not_raise() -> None:
    """Passing ldap_settings when no role needs LDAP must not fail or call out."""
    roles = [build_role(name="role1", users=["alice"])]

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        result = await resolve_role_members(
            roles,
            user_cls=Member,
            ldap_settings=_ldap_settings(),
            secret_manager_url="https://vault.example.com",
        )

    assert {m.org_username for m in result["role1"]} == {"alice"}
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_role_members_resolves_ldap_source() -> None:
    roles = [
        build_role(
            name="role1",
            users=["alice"],
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-a")
            ],
        )
    ]

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a", members=[LdapGroupMember(org_username="bob")]
                )
            ]
        )
        result = await resolve_role_members(
            roles,
            user_cls=Member,
            ldap_settings=_ldap_settings(),
            secret_manager_url="https://vault.example.com",
        )

    assert {m.org_username for m in result["role1"]} == {"alice", "bob"}


@pytest.mark.asyncio
async def test_resolve_role_members_dedup_prefers_explicit_user() -> None:
    """An explicit user's richer data wins over an LDAP-resolved duplicate."""
    roles = [
        build_role(
            name="role1",
            users=["shared-user"],
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-a")
            ],
        )
    ]

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a",
                    members=[LdapGroupMember(org_username="shared-user")],
                )
            ]
        )
        result = await resolve_role_members(
            roles,
            user_cls=Member,
            ldap_settings=_ldap_settings(),
            secret_manager_url="https://vault.example.com",
        )

    assert len(result["role1"]) == 1
    # MockUser fixture always sets github_username; but the important check
    # here is that only one member (not two duplicates) survived.
    assert result["role1"][0].org_username == "shared-user"


@pytest.mark.asyncio
async def test_resolve_role_members_resolves_app_interface_source(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """Feature parity with the sync resolve_role_members: the app-interface
    provider must be available on the async path too, unconditionally (no
    settings/secrets need to be passed in - unlike LDAP)."""
    mocker.patch.object(
        async_resolver,
        "resolve_app_interface_membership_source_async",
        return_value={("provider-a", "group1"): [Member(org_username="remote-user")]},
    )
    roles = [
        build_role(
            name="role1",
            users=["alice"],
            member_sources=[
                build_app_interface_membership_source(
                    name="provider-a",
                    group="group1",
                    source=app_interface_membership_provider,
                )
            ],
        )
    ]

    result = await resolve_role_members(roles, user_cls=Member)

    assert {m.org_username for m in result["role1"]} == {"alice", "remote-user"}


@pytest.mark.asyncio
async def test_resolve_role_members_unregistered_provider_raises() -> None:
    """A role referencing a provider with no registered async resolver errors.

    Plain duck-typed classes (not the pydantic MockRole/RoleMembershipSource
    fixtures) satisfy RoleWithMemberships/MembershipProvider/
    MembershipProviderSource structurally, letting us exercise a provider
    discriminator ("some-future-provider") that genuinely has no resolver
    registered, without needing a real GQL type for it.
    """

    class FakeSource:
        provider = "some-future-provider"

    class FakeProvider:
        name = "provider-x"
        has_audit_trail = False
        source = FakeSource()

    class FakeMemberSource:
        group = "group1"
        provider = FakeProvider()

    class FakeRole:
        name = "role1"
        users: list[User] = []
        bots: list[Bot] = []
        member_sources = [FakeMemberSource()]

    with pytest.raises(ValueError, match="No async resolver registered"):
        await resolve_role_members([FakeRole()], user_cls=Member)
