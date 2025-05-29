from collections.abc import Callable, Mapping
from typing import Any

import pytest
from pytest_mock import MockerFixture, MockType

from reconcile import ldap_users, mr_client_gateway
from reconcile.gql_definitions.common.ldap_settings import LdapSettingsV1
from reconcile.gql_definitions.common.users_with_paths import UserV1
from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.users_with_paths import get_users_with_paths


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ldap_users")


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("users_with_paths.yml")


@pytest.fixture
def users_with_paths(
    fx: Fixtures,
    data_factory: Callable[[type[UserV1], Mapping[str, Any]], Mapping[str, Any]],
    raw_fixture_data: dict[str, Any],
) -> list[UserV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "users": [
                data_factory(UserV1, item)
                for item in raw_fixture_data["usersWithPaths"]
            ]
        }

    return get_users_with_paths(q)


@pytest.fixture
def users_paths(users_with_paths: list[UserV1]) -> list[ldap_users.UserPaths]:
    return ldap_users.transform_users_with_paths(users_with_paths)


@pytest.fixture
def mocked_get_users_with_paths(
    mocker: MockerFixture, users_with_paths: list[UserV1]
) -> MockType:
    return mocker.patch(
        "reconcile.ldap_users.get_users_with_paths", return_value=users_with_paths
    )


@pytest.fixture
def mocked_get_ldap_settings(
    mocker: MockerFixture,
) -> MockType:
    return mocker.patch(
        "reconcile.ldap_users.get_ldap_settings",
        return_value=LdapSettingsV1(serverUrl="serverUrl", baseDn="baseDn"),
    )


@pytest.fixture
def mocked_get_ldap_users(
    mocker: MockerFixture,
) -> MockType:
    return mocker.patch(
        "reconcile.ldap_users.get_ldap_users", return_value={"username1"}
    )


@pytest.fixture
def mocked_mr_client_gateway(mocker: MockerFixture) -> MockType:
    return mocker.patch.object(mr_client_gateway, "init", autospec=True)


@pytest.fixture
def mocked_create_delete_user_app_interface(mocker: MockerFixture) -> MockType:
    return mocker.patch(
        "reconcile.ldap_users.CreateDeleteUserAppInterface", autospec=True
    )


@pytest.fixture
def mocked_create_delete_user_infra(mocker: MockerFixture) -> MockType:
    return mocker.patch("reconcile.ldap_users.CreateDeleteUserInfra", autospec=True)
