from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from typing import Any
from unittest.mock import Mock

import pytest

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.ldap_groups.integration import LdapGroupsIntegration
from reconcile.utils.internal_groups.client import NotFound
from reconcile.utils.internal_groups.models import (
    Entity,
    EntityType,
    Group,
)


def test_get_early_exit_desired_state(
    intg: LdapGroupsIntegration, roles: Sequence[RoleV1]
) -> None:
    intg.get_roles = lambda *args, **kwargs: roles  # type: ignore
    state = intg.get_early_exit_desired_state(query_func=lambda *args, **kwargs: None)
    assert "roles" in state


def test_ldap_groups_integration_get_managed_groups(
    s3_state_builder: Callable[[Mapping], Mock], intg: LdapGroupsIntegration
) -> None:
    state = s3_state_builder({})
    assert intg.get_managed_groups(state) == set()
    state = s3_state_builder({"get": {"managed_groups": ["group1", "group2"]}})
    assert intg.get_managed_groups(state) == {"group1", "group2"}


def test_ldap_groups_integration_set_managed_groups(
    s3_state_builder: Callable[[Mapping], Mock], intg: LdapGroupsIntegration
) -> None:
    state = s3_state_builder({})
    intg._managed_groups = {"group1", "group2"}
    intg.set_managed_groups(False, state)
    state.__setitem__.assert_called_once_with(
        "managed_groups", sorted(["group1", "group2"])
    )


def test_ldap_groups_integration_set_managed_groups_dry_run(
    s3_state_builder: Callable[[Mapping], Mock], intg: LdapGroupsIntegration
) -> None:
    state = s3_state_builder({})
    intg._managed_groups = {"group1", "group2"}
    intg.set_managed_groups(True, state)
    state.__setitem__.assert_not_called()


def test_ldap_groups_integration_get_roles(
    gql_class_factory: Callable, roles: Iterable[RoleV1]
) -> None:
    assert roles == [
        gql_class_factory(
            RoleV1,
            {
                "name": "no-ldap-group-set",
                "ldapGroup": None,
                "users": [{"org_username": "jeanluc"}, {"org_username": "riker"}],
            },
        ),
        gql_class_factory(
            RoleV1,
            {
                "name": "test-group",
                "ldapGroup": {"name": "ai-dev-test-group"},
                "users": [{"org_username": "pike"}, {"org_username": "uhura"}],
            },
        ),
        gql_class_factory(
            RoleV1,
            {
                "name": "test-group2",
                "ldapGroup": {
                    "name": "ai-dev-test-group-with-notes",
                    "notes": "Just a note",
                    "membersAreOwners": True,
                },
                "users": [{"org_username": "pike"}, {"org_username": "uhura"}],
            },
        ),
        gql_class_factory(
            RoleV1,
            {
                "name": "ldap-and-aws-role",
                "ldapGroup": {"name": "ai-dev-test-group-2"},
                "users": [{"org_username": "pike"}, {"org_username": "uhura"}],
                "user_policies": None,
                "aws_groups": [
                    {
                        "account": {
                            "name": "account-1",
                            "uid": "123456789",
                            "sso": True,
                        }
                    }
                ],
            },
        ),
        gql_class_factory(
            RoleV1,
            {
                "name": "aws-role-aws-groups",
                "ldapGroup": None,
                "users": [{"org_username": "pike"}, {"org_username": "uhura"}],
                "user_policies": None,
                "aws_groups": [
                    {
                        "account": {
                            "name": "account-1",
                            "uid": "123456789",
                            "sso": True,
                        }
                    }
                ],
            },
        ),
        gql_class_factory(
            RoleV1,
            {
                "name": "aws-role-user-policies",
                "ldapGroup": None,
                "users": [{"org_username": "pike"}, {"org_username": "uhura"}],
                "user_policies": [
                    {
                        "account": {
                            "name": "account-1",
                            "uid": "123456789",
                            "sso": True,
                        }
                    }
                ],
                "aws_groups": None,
            },
        ),
        gql_class_factory(
            RoleV1,
            {
                "name": "aws-role-multiple-accounts",
                "ldapGroup": None,
                "users": [{"org_username": "pike"}, {"org_username": "uhura"}],
                "user_policies": [
                    {
                        "account": {
                            "name": "user-policy-account-1",
                            "uid": "USER-POLICY-ACCOUNT-1-UID",
                            "sso": True,
                        }
                    },
                    {
                        "account": {
                            "name": "user-policy-account-2",
                            "uid": "USER-POLICY-ACCOUNT-2-UID",
                            "sso": False,
                        }
                    },
                    {
                        "account": {
                            "name": "user-policy-account-1",
                            "uid": "USER-POLICY-ACCOUNT-3-UID",
                            "sso": True,
                            "disable": {"integrations": ["ldap-groups"]},
                        }
                    },
                ],
                "aws_groups": [
                    {
                        "account": {
                            "name": "aws-groups-account-1",
                            "uid": "AWS-GROUPS-ACCOUNT-1-UID",
                            "sso": True,
                        }
                    },
                    {
                        "account": {
                            "name": "aws-groups-account-2",
                            "uid": "AWS-GROUPS-ACCOUNT-2-UID",
                            "sso": False,
                        }
                    },
                    {
                        "account": {
                            "name": "aws-groups-account-1",
                            "uid": "AWS-GROUPS-ACCOUNT-3-UID",
                            "sso": True,
                            "disable": {"integrations": ["ldap-groups"]},
                        }
                    },
                ],
            },
        ),
    ]


def test_ldap_groups_integration_get_roles_duplicates(
    intg: LdapGroupsIntegration,
    raw_fixture_data: dict[str, Any],
    data_factory: Callable,
) -> None:
    def q(*args: Any, **kwargs: Any) -> dict:
        roles = {
            "roles": [data_factory(RoleV1, item) for item in raw_fixture_data["roles"]]
        }
        # add a duplicate
        roles["roles"].append(roles["roles"][1])
        return roles

    with pytest.raises(ValueError):
        intg.get_roles(q)


def test_ldap_groups_integration_get_desired_groups_for_roles(
    intg: LdapGroupsIntegration,
    roles: Iterable[RoleV1],
    owners: list[Entity],
    groups: list[Group],
) -> None:
    resp = intg.get_desired_groups_for_roles(
        roles=roles,
        default_owners=owners,
        contact_list="email@example.org",
    )
    assert resp == groups


def test_ldap_groups_integration_get_desired_groups_for_aws_roles(
    intg: LdapGroupsIntegration,
    roles: Iterable[RoleV1],
    owners: list[Entity],
) -> None:
    assert intg.get_desired_groups_for_aws_roles(
        roles=roles, default_owners=owners, contact_list="email@example.org"
    ) == [
        Group(
            name="rover-prefix-123456789-ldap-and-aws-role",
            description="AWS account: 'account-1' Role: 'ldap-and-aws-role' Managed by qontract-reconcile",
            member_approval_type="self-service",
            contact_list="email@example.org",
            owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")],
            display_name="rover-prefix-123456789-ldap-and-aws-role",
            notes=None,
            rover_group_member_query=None,
            rover_group_inclusions=None,
            rover_group_exclusions=None,
            members=[
                Entity(type=EntityType.USER, id="pike"),
                Entity(type=EntityType.USER, id="uhura"),
            ],
            member_of=None,
            namespace=None,
        ),
        Group(
            name="rover-prefix-123456789-aws-role-aws-groups",
            description="AWS account: 'account-1' Role: 'aws-role-aws-groups' Managed by qontract-reconcile",
            member_approval_type="self-service",
            contact_list="email@example.org",
            owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")],
            display_name="rover-prefix-123456789-aws-role-aws-groups",
            notes=None,
            rover_group_member_query=None,
            rover_group_inclusions=None,
            rover_group_exclusions=None,
            members=[
                Entity(type=EntityType.USER, id="pike"),
                Entity(type=EntityType.USER, id="uhura"),
            ],
            member_of=None,
            namespace=None,
        ),
        Group(
            name="rover-prefix-123456789-aws-role-user-policies",
            description="AWS account: 'account-1' Role: 'aws-role-user-policies' Managed by qontract-reconcile",
            member_approval_type="self-service",
            contact_list="email@example.org",
            owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")],
            display_name="rover-prefix-123456789-aws-role-user-policies",
            notes=None,
            rover_group_member_query=None,
            rover_group_inclusions=None,
            rover_group_exclusions=None,
            members=[
                Entity(type=EntityType.USER, id="pike"),
                Entity(type=EntityType.USER, id="uhura"),
            ],
            member_of=None,
            namespace=None,
        ),
        Group(
            name="rover-prefix-USER-POLICY-ACCOUNT-1-UID-aws-role-multiple-accounts",
            description="AWS account: 'user-policy-account-1' Role: 'aws-role-multiple-accounts' Managed by qontract-reconcile",
            member_approval_type="self-service",
            contact_list="email@example.org",
            owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")],
            display_name="rover-prefix-USER-POLICY-ACCOUNT-1-UID-aws-role-multiple-accounts",
            notes=None,
            rover_group_member_query=None,
            rover_group_inclusions=None,
            rover_group_exclusions=None,
            members=[
                Entity(type=EntityType.USER, id="pike"),
                Entity(type=EntityType.USER, id="uhura"),
            ],
            member_of=None,
            namespace=None,
        ),
        Group(
            name="rover-prefix-AWS-GROUPS-ACCOUNT-1-UID-aws-role-multiple-accounts",
            description="AWS account: 'aws-groups-account-1' Role: 'aws-role-multiple-accounts' Managed by qontract-reconcile",
            member_approval_type="self-service",
            contact_list="email@example.org",
            owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")],
            display_name="rover-prefix-AWS-GROUPS-ACCOUNT-1-UID-aws-role-multiple-accounts",
            notes=None,
            rover_group_member_query=None,
            rover_group_inclusions=None,
            rover_group_exclusions=None,
            members=[
                Entity(type=EntityType.USER, id="pike"),
                Entity(type=EntityType.USER, id="uhura"),
            ],
            member_of=None,
            namespace=None,
        ),
    ]


def test_ldap_groups_integration_fetch_current_state(
    intg: LdapGroupsIntegration, internal_groups_client: Mock, group: Group
) -> None:
    internal_groups_client.group.side_effect = [group, NotFound()]
    assert intg.fetch_current_state(
        internal_groups_client=internal_groups_client, group_names=["group1"]
    ) == [group]


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry_run", "no_dry_run"])
def test_ldap_groups_integration_reconcile(
    intg: LdapGroupsIntegration,
    internal_groups_client: Mock,
    dry_run: bool,
) -> None:
    officers = Group(
        name="officers",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Officers",
        members=[
            Entity(type=EntityType.USER, id="chris-pike"),
            Entity(type=EntityType.USER, id="una"),
        ],
    )
    medical_crew = Group(
        name="medical-crew",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Medical Crew",
        members=[
            Entity(type=EntityType.USER, id="christine"),
            Entity(type=EntityType.USER, id="joseph m'benga"),
        ],
    )
    cerritos_crew = Group(
        name="cerritos-crew",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Cerritos Crossover",
        members=[
            Entity(type=EntityType.USER, id="beckett mariner"),
            Entity(type=EntityType.USER, id="brad boimler"),
        ],
    )
    love_couples = Group(
        name="love-couples",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Love Couples",
        members=[
            Entity(type=EntityType.USER, id="chris - marie"),
        ],
    )
    love_couples_new = Group(
        name="love-couples",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: New Love Couples",
        members=[
            Entity(type=EntityType.USER, id="chris - marie"),
            Entity(type=EntityType.USER, id="spock - christine"),
        ],
    )
    # must be a noop for DELETED_USERs
    nx_01_crew = Group(
        name="the-deleted-ones",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Medical Crew",
        members=[
            Entity(type=EntityType.USER, id="archer"),
            Entity(type=EntityType.USER, id="t'pol"),
        ],
    )
    nx_01_crew_deleted = Group(
        name="the-deleted-ones",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Medical Crew",
        members=[
            Entity(type=EntityType.DELETED_USER, id="archer"),
            Entity(type=EntityType.DELETED_USER, id="t'pol"),
        ],
    )

    desired_groups = [officers, medical_crew, love_couples_new, nx_01_crew_deleted]
    current_groups = [officers, cerritos_crew, love_couples, nx_01_crew]
    intg.reconcile(
        dry_run=dry_run,
        internal_groups_client=internal_groups_client,
        desired_groups=desired_groups,
        current_groups=current_groups,
    )
    if dry_run:
        internal_groups_client.create_group.assert_not_called()
        internal_groups_client.update_group.assert_not_called()
        internal_groups_client.delete_group.assert_not_called()
        return

    internal_groups_client.create_group.assert_called_once_with(medical_crew)
    internal_groups_client.delete_group.assert_called_once_with(cerritos_crew.name)
    internal_groups_client.update_group.assert_called_once_with(love_couples_new)

    assert sorted(intg._managed_groups) == sorted([
        "officers",
        "medical-crew",
        "love-couples",
        "the-deleted-ones",
    ])


def test_ldap_groups_integration_reconcile_sorted_members(
    intg: LdapGroupsIntegration, internal_groups_client: Mock
) -> None:
    officers_current = Group(
        name="officers",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Officers",
        members=[
            Entity(type=EntityType.USER, id="chris-pike"),
            Entity(type=EntityType.USER, id="una"),
        ],
    )
    officers_desired = Group(
        name="officers",
        description="Managed by qontract-reconcile",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="enterprise-lcars-1")],
        display_name="Star Trek - New Strange Worlds: Officers",
        members=[
            Entity(type=EntityType.USER, id="una"),
            Entity(type=EntityType.USER, id="chris-pike"),
        ],
    )

    intg.reconcile(
        dry_run=False,
        internal_groups_client=internal_groups_client,
        desired_groups=[officers_desired],
        current_groups=[officers_current],
    )

    internal_groups_client.create_group.assert_not_called()
    internal_groups_client.update_group.assert_not_called()
    internal_groups_client.delete_group.assert_not_called()
