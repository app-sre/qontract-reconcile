from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.ldap_groups.aws_groups import AWSGroupV1
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
def raw_fixture_data_aws_groups(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("aws_groups.yml")


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
def aws_groups(
    fx: Fixtures,
    data_factory: Callable[[type[AWSGroupV1], Mapping[str, Any]], Mapping[str, Any]],
    intg: LdapGroupsIntegration,
    raw_fixture_data_aws_groups: dict[str, Any],
) -> list[AWSGroupV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "aws_groups": [
                data_factory(AWSGroupV1, item)
                for item in raw_fixture_data_aws_groups["aws_groups"]
            ]
        }

    return intg.get_aws_groups(q)


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
