from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.cost_report.settings import CostReportSettingsV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.typed_queries.cost_report.app_names import App
from tools.cli_commands.cost_report.command import CostReportCommand
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ServiceReport
from tools.cli_commands.cost_report.response import ReportCostResponse

COST_MANAGEMENT_CONSOLE_BASE_URL = (
    "https://console.redhat.com/openshift/cost-management"
)


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.command.gql")


@pytest.fixture
def mock_cost_management_api(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.command.CostManagementApi",
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
        "tools.cli_commands.cost_report.command.get_app_interface_vault_settings",
        return_value=VAULT_SETTINGS,
    )


@pytest.fixture
def mock_create_secret_reader(mocker: MockerFixture) -> Any:
    mock = mocker.patch(
        "tools.cli_commands.cost_report.command.create_secret_reader",
        autospec=True,
    )
    mock.return_value.read_all_secret.return_value = {
        "api_base_url": "base_url",
        "token_url": "token_url",
        "client_id": "client_id",
        "client_secret": "client_secret",
        "scope": "scope",
        "console_base_url": COST_MANAGEMENT_CONSOLE_BASE_URL,
    }
    return mock


@pytest.fixture
def mock_get_cost_report_settings(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.command.get_cost_report_settings",
        return_value=COST_REPORT_SETTINGS,
    )


def test_cost_report_create(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_get_app_interface_vault_settings: Any,
    mock_create_secret_reader: Any,
    mock_get_cost_report_settings: Any,
) -> None:
    cost_report_command = CostReportCommand.create()

    assert isinstance(cost_report_command, CostReportCommand)
    assert cost_report_command.gql_api == mock_gql.get_api.return_value
    assert (
        cost_report_command.cost_management_console_base_url
        == COST_MANAGEMENT_CONSOLE_BASE_URL
    )
    assert (
        cost_report_command.cost_management_api == mock_cost_management_api.return_value
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
def cost_report_command(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_get_app_interface_vault_settings: Any,
    mock_create_secret_reader: Any,
    mock_get_cost_report_settings: Any,
) -> CostReportCommand:
    return CostReportCommand.create()


@pytest.fixture
def mock_get_app_names(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.command.get_app_names")


PARENT_APP = App(name="parent", parent_app_name=None)
CHILD_APP = App(name="child", parent_app_name="parent")


def test_cost_report_execute(
    cost_report_command: CostReportCommand,
    mock_get_app_names: Any,
    fx: Callable,
) -> None:
    expected_output = fx("empty_cost_report.md")
    mock_get_app_names.return_value = []

    output = cost_report_command.execute()

    assert output.rstrip() == expected_output.rstrip()


def test_cost_report_get_apps(
    cost_report_command: CostReportCommand,
    mock_get_app_names: Any,
) -> None:
    expected_apps = [PARENT_APP, CHILD_APP]
    mock_get_app_names.return_value = expected_apps

    apps = cost_report_command.get_apps()

    assert apps == expected_apps


def report_cost_response_builder(
    delta_value: int,
    delta_percent: int,
    total: int,
    service: str,
) -> ReportCostResponse:
    return ReportCostResponse.parse_obj({
        "meta": {
            "delta": {
                "value": delta_value,
                "percent": delta_percent,
            },
            "total": {
                "cost": {
                    "total": {
                        "value": total,
                        "units": "USD",
                    }
                }
            },
        },
        "data": [
            {
                "date": "2024-02",
                "services": [
                    {
                        "service": service,
                        "values": [
                            {
                                "delta_value": delta_value,
                                "delta_percent": delta_percent,
                                "cost": {
                                    "total": {
                                        "value": total,
                                        "units": "USD",
                                    }
                                },
                            }
                        ],
                    },
                ],
            }
        ],
    })


PARENT_APP_COST_RESPONSE = report_cost_response_builder(
    delta_value=100,
    delta_percent=10,
    total=1000,
    service="service1",
)

CHILD_APP_COST_RESPONSE = report_cost_response_builder(
    delta_value=200,
    delta_percent=20,
    total=2000,
    service="service2",
)

PARENT_APP_REPORT = Report(
    app_name="parent",
    parent_app_name=None,
    child_apps=[
        ChildAppReport(name="child", total=Decimal(2000)),
    ],
    child_apps_total=Decimal(2000),
    date="2024-02",
    services=[
        ServiceReport(
            service="service1",
            delta_value=Decimal(100),
            delta_percent=10,
            total=Decimal(1000),
        )
    ],
    services_total=Decimal(1000),
    services_delta_value=Decimal(100),
    services_delta_percent=10,
    total=Decimal(3000),
)

CHILD_APP_REPORT = Report(
    app_name="child",
    parent_app_name="parent",
    child_apps=[],
    child_apps_total=Decimal(0),
    date="2024-02",
    services=[
        ServiceReport(
            service="service2",
            delta_value=Decimal(200),
            delta_percent=20,
            total=Decimal(2000),
        )
    ],
    services_total=Decimal(2000),
    services_delta_value=Decimal(200),
    services_delta_percent=20,
    total=Decimal(2000),
)


def test_cost_report_get_reports(
    cost_report_command: CostReportCommand,
) -> None:
    expected_reports = {
        "parent": PARENT_APP_REPORT,
        "child": CHILD_APP_REPORT,
    }

    def side_effect(app_name: str) -> ReportCostResponse:
        match app_name:
            case "parent":
                return PARENT_APP_COST_RESPONSE
            case "child":
                return CHILD_APP_COST_RESPONSE
            case _:
                raise Exception("Unexpected app name")

    cost_report_command.cost_management_api.get_aws_costs_report.side_effect = (  # type: ignore[attr-defined]
        side_effect
    )

    reports = cost_report_command.get_reports([PARENT_APP, CHILD_APP])

    assert reports == expected_reports


def test_cost_report_render(
    cost_report_command: CostReportCommand,
    fx: Callable,
) -> None:
    expected_output = fx("cost_report.md")
    reports = {
        "parent": PARENT_APP_REPORT,
        "child": CHILD_APP_REPORT,
    }

    output = cost_report_command.render(reports)

    assert output == expected_output
