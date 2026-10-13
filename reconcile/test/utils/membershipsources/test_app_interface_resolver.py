from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from reconcile.gql_definitions.membershipsources.roles import (
    BotV1,
    UserV1,
)
from reconcile.utils.membershipsources import app_interface_resolver
from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source,
    resolve_app_interface_membership_source_async,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture

    from reconcile.gql_definitions.fragments.membership_source import (
        AppInterfaceMembershipProviderSourceV1,
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
    gql_api_mock = MagicMock()
    gql_api_mock.query = lambda *args, **kwargs: {
        "roles": [
            {
                "name": "role1",
                "labels": None,
                "path": "some/path.yml",
                "users": [user.model_dump(by_alias=True)],
                "bots": [bot.model_dump(by_alias=True)],
            }
        ],
    }
    gql_api_for_source_mock_ctx_mgr = MagicMock()
    gql_api_for_source_mock_ctx_mgr.__enter__.return_value = gql_api_mock
    gql_api_for_source_mock = mocker.patch.object(
        app_interface_resolver, "gql_api_for_source"
    )
    gql_api_for_source_mock.return_value = gql_api_for_source_mock_ctx_mgr

    groups = resolve_app_interface_membership_source(
        "provider",
        app_interface_membership_provider,
        {"role1"},
    )

    assert ("provider", "role1") in groups
    assert groups["provider", "role1"] == [user]


def test_resolve_raises_for_unresolved_role(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """A requested role absent from the response (unresolved) must fail closed.

    The remote role may have been renamed or removed; silently treating the
    omission as zero members would mean a role/Slack usergroup loses members
    without any indication something went wrong.
    """
    gql_api_mock = MagicMock()
    gql_api_mock.query = lambda *args, **kwargs: {"roles": []}
    gql_api_for_source_mock_ctx_mgr = MagicMock()
    gql_api_for_source_mock_ctx_mgr.__enter__.return_value = gql_api_mock
    gql_api_for_source_mock = mocker.patch.object(
        app_interface_resolver, "gql_api_for_source"
    )
    gql_api_for_source_mock.return_value = gql_api_for_source_mock_ctx_mgr

    with pytest.raises(RuntimeError, match="ghost-role"):
        resolve_app_interface_membership_source(
            "provider", app_interface_membership_provider, {"ghost-role"}
        )


def test_resolve_confirmed_empty_role_does_not_raise(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """A role present in the response with no users/bots is confirmed empty,
    not unresolved - this must not raise."""
    gql_api_mock = MagicMock()
    gql_api_mock.query = lambda *args, **kwargs: {
        "roles": [
            {
                "name": "role1",
                "labels": None,
                "path": "some/path.yml",
                "users": [],
                "bots": [],
            }
        ],
    }
    gql_api_for_source_mock_ctx_mgr = MagicMock()
    gql_api_for_source_mock_ctx_mgr.__enter__.return_value = gql_api_mock
    gql_api_for_source_mock = mocker.patch.object(
        app_interface_resolver, "gql_api_for_source"
    )
    gql_api_for_source_mock.return_value = gql_api_for_source_mock_ctx_mgr

    result = resolve_app_interface_membership_source(
        "provider", app_interface_membership_provider, {"role1"}
    )

    assert result == {("provider", "role1"): []}


def test_resolve_raises_naming_only_the_unresolved_roles(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """When some requested roles resolve and others don't, only the
    unresolved ones are named in the error."""
    gql_api_mock = MagicMock()
    gql_api_mock.query = lambda *args, **kwargs: {
        "roles": [
            {
                "name": "role1",
                "labels": None,
                "path": "some/path.yml",
                "users": [],
                "bots": [],
            }
        ],
    }
    gql_api_for_source_mock_ctx_mgr = MagicMock()
    gql_api_for_source_mock_ctx_mgr.__enter__.return_value = gql_api_mock
    gql_api_for_source_mock = mocker.patch.object(
        app_interface_resolver, "gql_api_for_source"
    )
    gql_api_for_source_mock.return_value = gql_api_for_source_mock_ctx_mgr

    with pytest.raises(RuntimeError) as exc_info:
        resolve_app_interface_membership_source(
            "provider", app_interface_membership_provider, {"role1", "ghost-role"}
        )

    assert "ghost-role" in str(exc_info.value)
    assert "role1" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_app_interface_membership_source_async_delegates_to_sync(
    mocker: MockerFixture,
    app_interface_membership_provider: AppInterfaceMembershipProviderSourceV1,
) -> None:
    """The async wrapper must run the same sync resolution (off the event
    loop) and return its result unchanged - this is what gives
    async_resolver.resolve_role_members feature parity with the sync
    resolve_role_members for the app-interface provider."""
    sync_mock = mocker.patch.object(
        app_interface_resolver, "resolve_app_interface_membership_source"
    )
    sync_mock.return_value = {("provider", "role1"): []}

    result = await resolve_app_interface_membership_source_async(
        "provider", app_interface_membership_provider, {"group1"}
    )

    assert result == {("provider", "role1"): []}
    sync_mock.assert_called_once_with(
        "provider", app_interface_membership_provider, {"group1"}
    )
