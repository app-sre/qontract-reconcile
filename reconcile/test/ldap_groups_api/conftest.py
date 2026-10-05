from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.ldap_groups_api.integration import (
    LdapGroupsApiIntegration,
    LdapGroupsApiIntegrationParams,
)
from reconcile.test.fixtures import Fixtures

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

SECRET_MANAGER_URL = "https://vault.example.com"
_MOD = "reconcile.ldap_groups_api.integration"


class _TestableIntegration(LdapGroupsApiIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ldap_groups")


@pytest.fixture
def integration() -> _TestableIntegration:
    return _TestableIntegration(
        LdapGroupsApiIntegrationParams(aws_sso_namespace="rover-prefix")
    )


@pytest.fixture
def roles(
    fx: Fixtures,
    gql_class_factory: Callable[[type[RoleV1], Mapping[str, Any]], RoleV1],
) -> list[RoleV1]:
    raw = fx.get_anymarkup("roles.yml")
    return [
        gql_class_factory(RoleV1, item)
        for item in raw["roles"]
        if item.get("ldapGroup")
    ][:2]
