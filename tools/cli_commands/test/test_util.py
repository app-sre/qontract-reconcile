from typing import Any
from unittest.mock import create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.cost_report.settings import CostReportSettingsV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.gql import GqlApi
from tools.cli_commands.cost_report.util import fetch_cost_report_secret
from tools.cli_commands.test.conftest import (
    COST_REPORT_SECRET,
)

VAULT_SETTINGS = AppInterfaceSettingsV1(vault=True)
COST_REPORT_SETTINGS = CostReportSettingsV1(
    credentials=VaultSecret(
        path="some-path",
        field="all",
        version=None,
        format=None,
    )
)


@pytest.fixture
def mock_get_app_interface_vault_settings(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.util.get_app_interface_vault_settings",
        return_value=VAULT_SETTINGS,
    )


@pytest.fixture
def mock_create_secret_reader(mocker: MockerFixture) -> Any:
    mock = mocker.patch(
        "tools.cli_commands.cost_report.util.create_secret_reader",
        autospec=True,
    )
    mock.return_value.read_all_secret.return_value = COST_REPORT_SECRET
    return mock


@pytest.fixture
def mock_get_cost_report_settings(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.util.get_cost_report_settings",
        return_value=COST_REPORT_SETTINGS,
    )


def test_fetch_cost_report_secret(
    mock_get_app_interface_vault_settings: Any,
    mock_create_secret_reader: Any,
    mock_get_cost_report_settings: Any,
) -> None:
    mock_gql_api = create_autospec(GqlApi)

    secret = fetch_cost_report_secret(mock_gql_api)

    assert secret == COST_REPORT_SECRET
    mock_get_app_interface_vault_settings.assert_called_once_with(mock_gql_api.query)
    mock_get_cost_report_settings.assert_called_once_with(mock_gql_api)
    mock_create_secret_reader.assert_called_once_with(use_vault=True)
    mock_create_secret_reader.return_value.read_all_secret.assert_called_once_with(
        COST_REPORT_SETTINGS.credentials
    )
