from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.cost_report.settings import CostReportSettingsV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from tools.cli_commands.cost_report.openshift import OpenShiftCostReportCommand


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.openshift.gql")


@pytest.fixture
def mock_cost_management_api(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift.CostManagementApi",
        autospec=True,
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
        "tools.cli_commands.cost_report.openshift.get_app_interface_vault_settings",
        return_value=VAULT_SETTINGS,
    )


@pytest.fixture
def mock_create_secret_reader(mocker: MockerFixture) -> Any:
    mock = mocker.patch(
        "tools.cli_commands.cost_report.openshift.create_secret_reader",
        autospec=True,
    )
    mock.return_value.read_all_secret.return_value = {
        "api_base_url": "base_url",
        "token_url": "token_url",
        "client_id": "client_id",
        "client_secret": "client_secret",
        "scope": "scope",
    }
    return mock


@pytest.fixture
def mock_get_cost_report_settings(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift.get_cost_report_settings",
        return_value=COST_REPORT_SETTINGS,
    )


def test_cost_report_create(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_get_app_interface_vault_settings: Any,
    mock_create_secret_reader: Any,
    mock_get_cost_report_settings: Any,
) -> None:
    openshift_cost_report_command = OpenShiftCostReportCommand.create()

    assert isinstance(openshift_cost_report_command, OpenShiftCostReportCommand)
    assert openshift_cost_report_command.gql_api == mock_gql.get_api.return_value
    assert (
        openshift_cost_report_command.cost_management_api
        == mock_cost_management_api.return_value
    )
    mock_cost_management_api.assert_called_once_with(
        base_url="base_url",
        token_url="token_url",
        client_id="client_id",
        client_secret="client_secret",
        scope=["scope"],
    )
    mock_get_app_interface_vault_settings.assert_called_once_with(
        mock_gql.get_api.return_value.query
    )
    mock_get_cost_report_settings.assert_called_once_with(mock_gql.get_api.return_value)
    mock_create_secret_reader.assert_called_once_with(use_vault=True)
    mock_create_secret_reader.return_value.read_all_secret.assert_called_once_with(
        COST_REPORT_SETTINGS.credentials
    )


@pytest.fixture
def openshift_cost_report_command(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_get_app_interface_vault_settings: Any,
    mock_create_secret_reader: Any,
    mock_get_cost_report_settings: Any,
) -> OpenShiftCostReportCommand:
    return OpenShiftCostReportCommand.create()


def test_cost_report_execute(
    openshift_cost_report_command: OpenShiftCostReportCommand,
) -> None:
    output = openshift_cost_report_command.execute()

    assert output == ""
