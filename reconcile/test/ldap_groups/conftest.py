from collections.abc import (
    Callable,
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
    return LdapGroupsIntegration(LdapGroupsIntegrationParams())


@pytest.fixture
def roles(
    fx: Fixtures,
    data_factory: Callable[[type[RoleV1], Mapping[str, Any]], Mapping[str, Any]],
    intg: LdapGroupsIntegration,
) -> list[RoleV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        raw_data = fx.get_anymarkup("roles.yml")
        return {"roles": [data_factory(RoleV1, item) for item in raw_data["roles"]]}

    return intg.get_roles(q)


@pytest.fixture
def group() -> Group:
    # keep in sync with fx/roles.yml
    return Group(
        name="ai-dev-test-group",
        description="Persisted App-Interface role. Managed by qontract-reconcile",
        member_approval_type="self-service",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")],
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
