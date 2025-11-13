from collections.abc import Callable

import pytest

from reconcile.gql_definitions.cost_report.settings import (
    CostReportAppInterfaceSettingsQueryData,
    CostReportSettingsV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.typed_queries.cost_report.settings import get_cost_report_settings
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.gql import GqlApi


@pytest.fixture
def cost_report_settings_data(
    gql_class_factory: Callable[..., CostReportAppInterfaceSettingsQueryData],
) -> CostReportAppInterfaceSettingsQueryData:
    return gql_class_factory(
        CostReportAppInterfaceSettingsQueryData,
        {
            "settings": [
                {
                    "costReport": {
                        "credentials": {
                            "path": "some-path",
                            "field": "all",
                        },
                    }
                }
            ]
        },
    )


def test_get_cost_report_settings(
    gql_api_builder: Callable[..., GqlApi],
    cost_report_settings_data: CostReportAppInterfaceSettingsQueryData,
) -> None:
    gql_api = gql_api_builder(cost_report_settings_data.dict(by_alias=True))
    expected_settings = CostReportSettingsV1(
        credentials=VaultSecret(
            path="some-path",
            field="all",
            version=None,
            format=None,
        )
    )

    settings = get_cost_report_settings(gql_api)

    assert settings == expected_settings


def test_get_cost_report_settings_when_no_data(
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    gql_api = gql_api_builder({"settings": None})

    with pytest.raises(AppInterfaceSettingsError) as e:
        get_cost_report_settings(gql_api)

    assert str(e.value) == "No settings configured"


def test_get_cost_report_settings_when_no_cost_report_settings(
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    gql_api = gql_api_builder({"settings": [{"costReport": None}]})

    with pytest.raises(AppInterfaceSettingsError) as e:
        get_cost_report_settings(gql_api)

    assert str(e.value) == "No cost report configured"
