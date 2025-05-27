from collections.abc import Callable, Mapping
from typing import Any

import pytest

from reconcile import ldap_users
from reconcile.gql_definitions.common.users_paths import UserV1
from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.users_paths import get_users_paths


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ldap_users")


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("users_paths.yml")


@pytest.fixture
def raw_users_paths(
    fx: Fixtures,
    data_factory: Callable[[type[UserV1], Mapping[str, Any]], Mapping[str, Any]],
    raw_fixture_data: dict[str, Any],
) -> list[UserV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "users": [
                data_factory(UserV1, item) for item in raw_fixture_data["usersPaths"]
            ]
        }

    return get_users_paths(q)


@pytest.fixture
def users_paths(raw_users_paths: list[UserV1]) -> list[ldap_users.UserPaths]:
    return ldap_users.transform_users_paths(raw_users_paths)
