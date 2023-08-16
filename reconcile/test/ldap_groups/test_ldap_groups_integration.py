from collections.abc import (
    Callable,
    Iterable,
    Mapping,
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
    intg.set_managed_groups(state)
    state.__setitem__.assert_called_once_with("managed_groups", ["group1", "group2"])


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


def test_ldap_groups_integration_fetch_desired_state(
    intg: LdapGroupsIntegration,
    roles: Iterable[RoleV1],
    owners: Iterable[Entity],
    group: Group,
) -> None:
    assert intg.fetch_desired_state(
        roles=roles,
        owners=owners,
        contact_list="email@example.org",
    ) == [group]


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
    desired_groups = [officers, medical_crew, love_couples_new]
    current_groups = [officers, cerritos_crew, love_couples]
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

    assert sorted(intg._managed_groups) == sorted(
        ["officers", "medical-crew", "love-couples"]
    )
