from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.ldap_groups.integration import (
    LdapGroupsIntegration,
    LdapGroupsIntegrationParams,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils.internal_groups.client import InternalGroupsClient
from reconcile.utils.internal_groups.models import (
    Entity,
    EntityType,
    Group,
)


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ldap_groups")


@pytest.fixture
def intg() -> LdapGroupsIntegration:
    return LdapGroupsIntegration(
        LdapGroupsIntegrationParams(aws_sso_namespace="rover-prefix")
    )


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("roles.yml")


@pytest.fixture
def roles(
    fx: Fixtures,
    data_factory: Callable[[type[RoleV1], Mapping[str, Any]], Mapping[str, Any]],
    intg: LdapGroupsIntegration,
    raw_fixture_data: dict[str, Any],
) -> list[RoleV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "roles": [data_factory(RoleV1, item) for item in raw_fixture_data["roles"]]
        }

    return intg.get_roles(q)


@pytest.fixture
def group(owners: Iterable[Entity]) -> Group:
    # keep in sync with fx/roles.yml
    return Group(
        name="ai-dev-test-group",
        description="Persisted App-Interface role. Managed by qontract-reconcile",
        member_approval_type="self-service",
        contact_list="email@example.org",
        owners=owners,
        display_name="ai-dev-test-group (App-Interface))",
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
    )


@pytest.fixture
def group2(owners: list[Entity]) -> Group:
    # keep in sync with fx/roles.yml
    return Group(
        name="ai-dev-test-group-with-notes",
        description="Persisted App-Interface role. Managed by qontract-reconcile",
        member_approval_type="self-service",
        contact_list="email@example.org",
        owners=owners
        + [
            Entity(type=EntityType.USER, id="pike"),
            Entity(type=EntityType.USER, id="uhura"),
        ],
        display_name="ai-dev-test-group-with-notes (App-Interface))",
        notes="Just a note",
        rover_group_member_query=None,
        rover_group_inclusions=None,
        rover_group_exclusions=None,
        members=[
            Entity(type=EntityType.USER, id="pike"),
            Entity(type=EntityType.USER, id="uhura"),
        ],
        member_of=None,
        namespace=None,
    )


@pytest.fixture
def group3(owners: Iterable[Entity]) -> Group:
    # keep in sync with fx/roles.yml
    return Group(
        name="ai-dev-test-group-2",
        description="Persisted App-Interface role. Managed by qontract-reconcile",
        member_approval_type="self-service",
        contact_list="email@example.org",
        owners=owners,
        display_name="ai-dev-test-group-2 (App-Interface))",
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
    )


@pytest.fixture
def groups(group: Group, group2: Group, group3: Group) -> list[Group]:
    return [group, group2, group3]


@pytest.fixture
def owners() -> list[Entity]:
    return [
        Entity(
            type=EntityType.SERVICE_ACCOUNT,
            id="service-account-1",
        )
    ]


@pytest.fixture
def internal_groups_client(mocker: MockerFixture) -> Mock:
    return mocker.create_autospec(spec=InternalGroupsClient)
