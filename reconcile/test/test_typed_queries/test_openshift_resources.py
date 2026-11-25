from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.gql_definitions.openshift_resources.settings import (
    DEFINITION,
    AppInterfaceSettingsV1,
)
from reconcile.typed_queries import openshift_resources
from reconcile.utils.exceptions import AppInterfaceSettingsError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    "settings",
    [
        None,
        [],
        [
            AppInterfaceSettingsV1(repoUrl="https://first.example.com", vault=True),
            AppInterfaceSettingsV1(repoUrl="https://second.example.com", vault=False),
        ],
    ],
)
def test_settings_must_be_unique(
    mocker: MockerFixture, settings: list[AppInterfaceSettingsV1] | None
) -> None:
    query = mocker.Mock(
        return_value={
            "settings": [item.model_dump(by_alias=True) for item in settings]
            if settings is not None
            else None
        }
    )

    with pytest.raises(AppInterfaceSettingsError, match="not uniquely defined"):
        openshift_resources.get_openshift_resources_settings(query_func=query)

    query.assert_called_once_with(DEFINITION)


@pytest.mark.parametrize("use_vault", [True, False])
def test_settings_query_returns_only_resource_settings(
    mocker: MockerFixture, use_vault: bool
) -> None:
    expected = AppInterfaceSettingsV1(
        repoUrl="https://git.example.com/app-interface", vault=use_vault
    )
    query = mocker.Mock(return_value={"settings": [expected.model_dump(by_alias=True)]})

    assert (
        openshift_resources.get_openshift_resources_settings(query_func=query)
        == expected
    )
    assert set(AppInterfaceSettingsV1.model_fields) == {"repo_url", "vault"}
    query.assert_called_once_with(DEFINITION)


def test_settings_use_current_graphql_client_without_global_cache(
    mocker: MockerFixture,
) -> None:
    client = mocker.patch.object(openshift_resources.gql, "get_api").return_value
    client.query.side_effect = [
        {"settings": [{"repoUrl": "https://first.example.com", "vault": True}]},
        {"settings": [{"repoUrl": "https://second.example.com", "vault": False}]},
    ]

    assert (
        openshift_resources.get_openshift_resources_settings().repo_url
        == "https://first.example.com"
    )
    assert (
        openshift_resources.get_openshift_resources_settings().repo_url
        == "https://second.example.com"
    )
    assert client.query.call_count == 2
