from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from typing import Any
from unittest.mock import Mock

import pytest

from reconcile.gql_definitions.ldap_groups.aws_groups import AWSGroupV1
from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.ldap_groups.integration import (
    LdapGroupsIntegration,
    get_aws_group_ldap_name,
)
from reconcile.utils.internal_groups.client import NotFound
from reconcile.utils.internal_groups.models import (
    Entity,
    EntityType,
    Group,
)


def test_get_aws_group_ldap_name(aws_groups: Sequence[AWSGroupV1]) -> None:
    assert (
        get_aws_group_ldap_name("prefix", aws_groups[0])
        == "prefix-123456789-shiny-Group"
    )


def test_get_early_exit_desired_state(
    intg: LdapGroupsIntegration,
    roles: Sequence[RoleV1],
    aws_groups: Sequence[AWSGroupV1],
) -> None:
    intg.get_roles = lambda *args, **kwargs: roles  # type: ignore
    intg.get_aws_groups = lambda *args, **kwargs: aws_groups  # type: ignore
    state = intg.get_early_exit_desired_state(query_func=lambda *args, **kwargs: None)
    assert "roles" in state
    assert "aws_groups" in state


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
                "name": "test-group",
                "ldapGroup": "ai-dev-test-group",
                "users": [
                    {"org_username": "pike"},
                    {"org_username": "uhura"},
                ],
            },
        )
    ]


def test_ldap_groups_integration_get_aws_groups(
    gql_class_factory: Callable, aws_groups: Sequence[AWSGroupV1]
) -> None:
    assert aws_groups == [
        gql_class_factory(
            AWSGroupV1,
            {
                "name": "shiny-Group",
                "account": {
                    "name": "aws-account-1",
                    "uid": "123456789",
                    "sso": True,
                },
                "roles": [
                    {
                        "users": [
                            {"org_username": "user-1"},
                            {
                                "org_username": "user-2",
                            },
                        ]
                    }
                ],
            },
        ),
        gql_class_factory(
            AWSGroupV1,
            {
                "name": "second-Group",
                "account": {
                    "name": "aws-account-1",
                    "uid": "987654321",
                    "sso": None,
                },
                "roles": [
                    {
                        "users": [
                            {"org_username": "user-1"},
                        ]
                    }
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
    owners: Iterable[Entity],
    group: Group,
) -> None:
    assert intg.get_desired_groups_for_roles(
        roles=roles,
        owners=owners,
        contact_list="email@example.org",
    ) == [group]


def test_ldap_groups_integration_get_desired_groups_for_aws_groups(
    intg: LdapGroupsIntegration,
    aws_groups: Iterable[AWSGroupV1],
    owners: Iterable[Entity],
) -> None:
    assert intg.get_desired_groups_for_aws_groups(
        aws_groups=aws_groups,
        owners=owners,
        contact_list="email@example.org",
    ) == [
        Group(
            name="rover-prefix-123456789-shiny-Group",
            description="AWS account: 'aws-account-1' Role: 'shiny-Group' Managed by qontract-reconcile",
            member_approval_type="self-service",
            contact_list="email@example.org",
            owners=owners,
            display_name="rover-prefix-123456789-shiny-Group",
            notes=None,
            rover_group_member_query=None,
            rover_group_inclusions=None,
            rover_group_exclusions=None,
            members=[
                Entity(type=EntityType.USER, id="user-1"),
                Entity(type=EntityType.USER, id="user-2"),
            ],
            member_of=None,
            namespace=None,
        ),
        Group(
            name="rover-prefix-987654321-second-Group",
            description="AWS account: 'aws-account-1' Role: 'second-Group' Managed by qontract-reconcile",
            member_approval_type="self-service",
            contact_list="email@example.org",
            owners=owners,
            display_name="rover-prefix-987654321-second-Group",
            notes=None,
            rover_group_member_query=None,
            rover_group_inclusions=None,
            rover_group_exclusions=None,
            members=[Entity(type=EntityType.USER, id="user-1")],
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
