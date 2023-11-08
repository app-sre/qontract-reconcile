from typing import Callable
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.membership_source import (
    AppInterfaceMembershipProviderSourceV1,
)
from reconcile.gql_definitions.membershipsources.roles import (
    BotV1,
    UserV1,
)
from reconcile.utils.membershipsources import app_interface_resolver
from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source,
)


@pytest.fixture
def user(gql_class_factory: Callable[..., UserV1]) -> UserV1:
    return gql_class_factory(
        UserV1,
        {
            "name": "user",
            "org_username": "user",
            "tag_on_merge_requests": False,
        },
    )


@pytest.fixture
def bot(gql_class_factory: Callable[..., BotV1]) -> BotV1:
    return gql_class_factory(
        BotV1,
        {
            "name": "bot",
            "org_username": "bot",
        },
    )


def test_resolve_app_interface_membership_source(
    mocker: MockerFixture,
    user: UserV1,
    bot: BotV1,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    gql_query_func_for_source_mock_ctx_mgr = MagicMock()
    gql_query_func_for_source_mock_ctx_mgr.__enter__.return_value = (
        lambda *args, **kwargs: {
            "roles": [
                {
                    "name": "role1",
                    "labels": None,
                    "path": "some/path.yml",
                    "users": [user.dict(by_alias=True)],
                    "bots": [bot.dict(by_alias=True)],
                }
            ],
        }
    )
    gql_query_func_for_source_mock = mocker.patch.object(
        app_interface_resolver, "gql_query_func_for_source"
    )
    gql_query_func_for_source_mock.return_value = gql_query_func_for_source_mock_ctx_mgr
    groups = resolve_app_interface_membership_source(
        "provider",
        app_interface_membership_provider,
        {"group1"},
    )

    assert ("provider", "role1") in groups
    assert {m.org_username for m in groups[("provider", "role1")]} == {"user", "bot"}
