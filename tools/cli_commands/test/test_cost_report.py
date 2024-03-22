from decimal import Decimal
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.typed_queries.cost_report.app_names import App
from tools.cli_commands.cost_report.command import CostReportCommand
from tools.cli_commands.cost_report.model import Report, ServiceReport
from tools.cli_commands.cost_report.response import ReportCostResponse


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.command.gql")


@pytest.fixture
def mock_cost_management_api(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.command.CostManagementApi",
        autospec=True,
    )


def test_cost_report_create(
    mock_gql: Any,
    mock_cost_management_api: Any,
) -> None:
    cost_report_command = CostReportCommand.create()

    assert isinstance(cost_report_command, CostReportCommand)
    assert cost_report_command.gql_api == mock_gql.get_api.return_value
    assert (
        cost_report_command.cost_management_api == mock_cost_management_api.return_value
    )


@pytest.fixture
def cost_report_command(
    mock_gql: Any,
    mock_cost_management_api: Any,
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
) -> None:
    mock_get_app_names.return_value = []
    assert cost_report_command.execute() == ""


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
    delta_percentage: int,
    total: int,
    service: str,
) -> ReportCostResponse:
    return ReportCostResponse.parse_obj({
        "meta": {
            "delta": {
                "value": delta_value,
                "percent": delta_percentage,
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
                                "delta_percent": delta_percentage,
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
    delta_percentage=10,
    total=1000,
    service="service1",
)

CHILD_APP_COST_RESPONSE = report_cost_response_builder(
    delta_value=200,
    delta_percentage=20,
    total=2000,
    service="service2",
)

PARENT_APP_REPORT = Report(
    app_name="parent",
    parent_app_name=None,
    child_apps=["child"],
    child_apps_total=Decimal(2000),
    date="2024-02",
    services=[
        ServiceReport(
            service="service1",
            delta_value=Decimal(100),
            delta_percentage=10,
            total=Decimal(1000),
        )
    ],
    services_total=Decimal(1000),
    services_delta_value=Decimal(100),
    services_delta_percentage=10,
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
            delta_percentage=20,
            total=Decimal(2000),
        )
    ],
    services_total=Decimal(2000),
    services_delta_value=Decimal(200),
    services_delta_percentage=20,
    total=Decimal(2000),
)


def test_cost_report_get_reports(
    cost_report_command: CostReportCommand,
) -> None:
    expected_reports = {
        "parent": PARENT_APP_REPORT,
        "child": CHILD_APP_REPORT,
    }

    def side_effect(app_name):
        match app_name:
            case "parent":
                return PARENT_APP_COST_RESPONSE
            case "child":
                return CHILD_APP_COST_RESPONSE

    cost_report_command.cost_management_api.get_aws_costs_report.side_effect = (
        side_effect
    )

    reports = cost_report_command.get_reports([PARENT_APP, CHILD_APP])

    assert reports == expected_reports


def test_cost_report_render(cost_report_command: CostReportCommand) -> None:
    assert cost_report_command.render({}) == ""
