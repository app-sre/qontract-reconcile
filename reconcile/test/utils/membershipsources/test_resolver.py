from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.membership_source import (
    AppInterfaceMembershipProviderSourceV1,
    MembershipProviderV1,
)
from reconcile.test.utils.membershipsources.fixtures import (
    build_app_interface_membership_source,
    build_role,
)
from reconcile.utils.membershipsources import resolver
from reconcile.utils.membershipsources.models import (
    RoleBot,
    RoleUser,
)
from reconcile.utils.membershipsources.resolver import (
    GroupResolverJob,
    build_resolver_jobs,
    resolve_groups,
)


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


def test_resolve_groups_provider_dispatching(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    a_i_resolver_mock = mocker.patch.object(
        resolver, "resolve_app_interface_membership_source"
    )
    job = GroupResolverJob(
        provider=MembershipProviderV1(
            name="provider",
            hasAuditTrail=True,
            source=app_interface_membership_provider,
        ),
        groups={"group-1", "group-2"},
    )
    resolve_groups(job)
    a_i_resolver_mock.assert_called_once_with(
        job.provider.name, job.provider.source, job.groups
    )


def test_resolve_role_members(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    a_i_resolver_mock = mocker.patch.object(
        resolver, "resolve_app_interface_membership_source"
    )
    a_i_resolver_mock.return_value = {
        ("provider-a", "group1"): [
            RoleUser(name="a-i-user", org_username="a-i-user"),
            RoleBot(name="a-i-bot", org_username="a-i-bot"),
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

    members_by_role = resolver.resolve_role_members(roles)
    assert "role1" in members_by_role
    assert {u.org_username for u in members_by_role["role1"]} == {
        "local-user",
        "local-bot",
        "a-i-user",
        "a-i-bot",
    }
