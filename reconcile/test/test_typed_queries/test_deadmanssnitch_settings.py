from collections.abc import (
    Callable,
    Mapping,
)
from typing import TYPE_CHECKING, cast

import pytest

from reconcile.gql_definitions.common.app_interface_dms_settings import (
    DEFINITION,
    DeadMansSnitchSettingsQueryData,
)
from reconcile.typed_queries.app_interface_deadmanssnitch_settings import (
    get_deadmanssnitch_settings,
)
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.gql import GqlApi

if TYPE_CHECKING:
    from unittest.mock import MagicMock


def test_no_settings(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., DeadMansSnitchSettingsQueryData],
) -> None:
    data = gql_class_factory(DeadMansSnitchSettingsQueryData, [])
    api = gql_api_builder(data.model_dump(by_alias=True))
    with pytest.raises(AppInterfaceSettingsError):
        get_deadmanssnitch_settings(gql_api=api)


def test_get_clusters(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., DeadMansSnitchSettingsQueryData],
) -> None:
    data = gql_class_factory(
        DeadMansSnitchSettingsQueryData,
        {
            "settings": [
                {
                    "deadMansSnitchSettings": {
                        "alertMailAddresses": ["test_mail"],
                        "notesLink": "test_link",
                        "snitchesPath": "test_path",
                        "tokenCreds": {"path": "xyz", "field": "xyz"},
                        "tags": ["test-tags"],
                        "interval": "15_minute",
                        "alertType": "Heartbeat",
                    }
                }
            ]
        },
    )
    api = gql_api_builder(data.model_dump(by_alias=True))
    settings = get_deadmanssnitch_settings(gql_api=api)
    assert settings.alert_mail_addresses == ["test_mail"]
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION)
