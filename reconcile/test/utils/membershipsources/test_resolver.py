from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from reconcile.gql_definitions.fragments.membership_source import (
    AppInterfaceMembershipProviderSourceV1,
    MembershipProviderSourceV1,
    MembershipProviderV1,
)
from reconcile.test.utils.membershipsources.fixtures import (
    CustomRole,
    build_app_interface_membership_source,
    build_ldap_membership_source,
    build_role,
)
from reconcile.utils.membershipsources import async_resolver, resolver
from reconcile.utils.membershipsources.resolver import (
    GroupResolverJob,
    build_resolver_jobs,
    resolve_groups,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from reconcile.utils.membershipsources.models import ProviderMember


class Member(BaseModel, extra="ignore"):
    """Minimal user_cls used to exercise the resolver in isolation."""

    name: str = ""
    org_username: str


@pytest.mark.parametrize("github_username", [None, "", "alice-gh"])
def test_github_membership_filter_is_silent(
    github_username: str | None, mocker: MockerFixture
) -> None:
    member = mocker.Mock(org_username="alice", github_username=github_username)
    warning = mocker.patch("logging.warning")
    assert resolver.has_github_username(member) is bool(github_username)
    warning.assert_not_called()


def test_build_resolver_jobs_grouping(
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """
    Test grouping of membership sources by provider.
    """
    roles = [
        build_role(
            name="role1",
            member_sources=[
                build_app_interface_membership_source(
                    name="provider-a",
                    group="group1",
                    source=app_interface_membership_provider,
                )
            ],
        ),
        build_role(
            name="role2",
            member_sources=[
                build_app_interface_membership_source(
                    name="provider-a",
                    group="group2",
                    source=app_interface_membership_provider,
                )
            ],
        ),
        build_role(
            name="role3",
            member_sources=[
                build_app_interface_membership_source(
                    name="provider-b",
                    group="group3",
                    source=app_interface_membership_provider,
                )
            ],
        ),
        build_role(name="role4"),
    ]

    jobs = {job.provider.name: job for job in build_resolver_jobs(roles)}
    assert len(jobs) == 2
    assert jobs["provider-a"].groups == {"group1", "group2"}
    assert jobs["provider-b"].groups == {"group3"}


def test_resolve_groups_dispatches_by_provider_string(
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """Test resolve_groups picks the resolver registered for the source's
    provider discriminator - no hidden/global dispatch."""
    calls: list[tuple[str, MembershipProviderSourceV1, set[str]]] = []

    def fake_resolver(
        provider_name: str, source: MembershipProviderSourceV1, groups: set[str]
    ) -> dict[tuple[str, str], list[ProviderMember]]:
        calls.append((provider_name, source, groups))
        return {}

    job = GroupResolverJob(
        provider=MembershipProviderV1(
            name="provider",
            hasAuditTrail=True,
            source=app_interface_membership_provider,
        ),
        groups={"group-1", "group-2"},
    )

    result = resolve_groups(job, resolvers={"app-interface": fake_resolver})

    assert calls == [(job.provider.name, job.provider.source, job.groups)]
    assert result == {}


def test_resolve_groups_raises_for_unregistered_provider() -> None:
    job = GroupResolverJob(
        provider=MembershipProviderV1(
            name="corp-ldap",
            hasAuditTrail=False,
            source=MembershipProviderSourceV1(provider="ldap"),
        ),
        groups={"team-a"},
    )

    try:
        resolve_groups(job, resolvers={})
    except ValueError as e:
        assert "ldap" in e.args
    else:
        raise AssertionError("expected ValueError")


def test_resolve_role_members(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    a_i_resolver_mock = mocker.patch.object(
        resolver, "resolve_app_interface_membership_source"
    )
    a_i_resolver_mock.return_value = {
        ("provider-a", "group1"): [
            Member(name="a-i-user", org_username="a-i-user"),
            Member(name="a-i-bot", org_username="a-i-bot"),
        ]
    }
    roles = [
        build_role(
            name="role1",
            users=["local-user"],
            bots=["local-bot"],
            member_sources=[
                build_app_interface_membership_source(
                    name="provider-a",
                    group="group1",
                    source=app_interface_membership_provider,
                )
            ],
        ),
    ]

    members_by_role = resolver.resolve_role_members(
        roles, user_cls=Member, role_cls=CustomRole[Member]
    )
    assert members_by_role[0].name == "role1"
    assert {u.org_username for u in members_by_role[0].users} == {
        "local-user",
        "a-i-user",
        "a-i-bot",
    }


def test_resolve_role_members_dedup_prefers_explicit_user(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """An explicit user wins over a source-resolved member sharing org_username."""
    a_i_resolver_mock = mocker.patch.object(
        resolver, "resolve_app_interface_membership_source"
    )
    a_i_resolver_mock.return_value = {
        ("provider-a", "group1"): [
            Member(name="from-source", org_username="shared-user"),
        ]
    }
    roles = [
        build_role(
            name="role1",
            users=["shared-user"],
            member_sources=[
                build_app_interface_membership_source(
                    name="provider-a",
                    group="group1",
                    source=app_interface_membership_provider,
                )
            ],
        ),
    ]

    members_by_role = resolver.resolve_role_members(
        roles, user_cls=Member, role_cls=CustomRole[Member]
    )
    assert len(members_by_role[0].users) == 1
    assert members_by_role[0].users[0].name == "shared-user"


def test_resolve_role_members_ldap_source(mocker: MockerFixture) -> None:
    """Test resolve_role_members resolves LDAP-sourced members end-to-end,
    given injected ldap_settings/secret_manager_url."""

    fake_resolve = mocker.AsyncMock(
        return_value={("corp-ldap", "team-a"): [Member(org_username="ldap-user")]}
    )

    mocker.patch.object(
        async_resolver, "create_ldap_membership_resolver", return_value=fake_resolve
    )
    roles = [
        build_role(
            name="role1",
            users=["local-user"],
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-a")
            ],
        ),
    ]

    members_by_role = resolver.resolve_role_members(
        roles,
        user_cls=Member,
        ldap_settings=MagicMock(),
        secret_manager_url="https://vault.example.com",
        role_cls=CustomRole[Member],
    )
    assert {u.org_username for u in members_by_role[0].users} == {
        "local-user",
        "ldap-user",
    }


@pytest.mark.usefixtures("ldap_endpoint")
def test_resolve_role_members_ldap_source_loads_settings(mocker: MockerFixture) -> None:
    """The public resolver loads configuration when LDAP dependencies are omitted."""
    roles = [
        build_role(
            name="role1",
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="source-team")
            ],
        ),
    ]

    lookup = mocker.spy(async_resolver, "get_ldap_settings")
    assert resolver.resolve_role_members(
        roles, user_cls=Member, role_cls=CustomRole[Member]
    )[0].users == [Member(name="Alice Example", org_username="alice")]
    lookup.assert_called_once_with(query_func=None)


def test_resolve_role_members_ldap_settings_without_secret_manager_url_raises() -> None:
    roles = [build_role(name="role1", users=["alice"])]

    try:
        resolver.resolve_role_members(roles, user_cls=Member, ldap_settings=MagicMock())
    except ValueError as e:
        assert "secret_manager_url is required" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_build_resolver_jobs_ignores_roles_without_member_sources() -> None:
    """Test resolve_role_members returns local members unchanged when no
    memberSources are present, without triggering any provider resolution."""
    roles = [build_role(name="role1", users=["local-user"])]

    members_by_role = resolver.resolve_role_members(
        roles, user_cls=Member, role_cls=CustomRole[Member]
    )

    assert {u.org_username for u in members_by_role[0].users} == {"local-user"}
    assert build_resolver_jobs(roles) == []
