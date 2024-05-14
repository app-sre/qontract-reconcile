from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.typed_queries.cost_report.app_names import App
from tools.cli_commands.cost_report.aws import AwsCostReportCommand
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ReportItem
from tools.cli_commands.cost_report.response import AwsReportCostResponse
from tools.cli_commands.test.conftest import (
    COST_REPORT_SECRET,
)

COST_MANAGEMENT_CONSOLE_BASE_URL = (
    "https://console.redhat.com/openshift/cost-management"
)


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.aws.gql")


@pytest.fixture
def mock_cost_management_api(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.aws.CostManagementApi",
        autospec=True,
    )


@pytest.fixture
def mock_fetch_cost_report_secret(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.aws.fetch_cost_report_secret",
        return_value=COST_REPORT_SECRET,
    )


def test_aws_cost_report_create(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_fetch_cost_report_secret: Any,
) -> None:
    cost_report_command = AwsCostReportCommand.create()

    assert isinstance(cost_report_command, AwsCostReportCommand)
    assert cost_report_command.gql_api == mock_gql.get_api.return_value
    assert (
        cost_report_command.cost_management_console_base_url
        == COST_MANAGEMENT_CONSOLE_BASE_URL
    )
    assert (
        cost_report_command.cost_management_api
        == mock_cost_management_api.create_from_secret.return_value
    )
    assert cost_report_command.thread_pool_size == 10
    mock_cost_management_api.create_from_secret.assert_called_once_with(
        COST_REPORT_SECRET
    )
    mock_fetch_cost_report_secret.assert_called_once_with(mock_gql.get_api.return_value)


@pytest.fixture
def aws_cost_report_command(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_fetch_cost_report_secret: Any,
) -> AwsCostReportCommand:
    return AwsCostReportCommand.create()


@pytest.fixture
def mock_get_app_names(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.aws.get_app_names")


PARENT_APP = App(name="parent", parent_app_name=None)
CHILD_APP = App(name="child", parent_app_name="parent")


def test_aws_cost_report_execute(
    aws_cost_report_command: AwsCostReportCommand,
    mock_get_app_names: Any,
    fx: Callable,
) -> None:
    expected_output = fx("empty_aws_cost_report.md")
    mock_get_app_names.return_value = []

    output = aws_cost_report_command.execute()

    assert output.rstrip() == expected_output.rstrip()


def test_aws_cost_report_get_apps(
    aws_cost_report_command: AwsCostReportCommand,
    mock_get_app_names: Any,
) -> None:
    expected_apps = [PARENT_APP, CHILD_APP]
    mock_get_app_names.return_value = expected_apps

    apps = aws_cost_report_command.get_apps()

    assert apps == expected_apps


def aws_report_cost_response_builder(
    delta_value: int,
    delta_percent: int,
    total: int,
    service: str,
) -> AwsReportCostResponse:
    return AwsReportCostResponse.parse_obj({
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


PARENT_APP_COST_RESPONSE = aws_report_cost_response_builder(
    delta_value=100,
    delta_percent=10,
    total=1000,
    service="service1",
)

CHILD_APP_COST_RESPONSE = aws_report_cost_response_builder(
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
    items=[
        ReportItem(
            name="service1",
            delta_value=Decimal(100),
            delta_percent=10,
            total=Decimal(1000),
        )
    ],
    items_total=Decimal(1000),
    items_delta_value=Decimal(100),
    items_delta_percent=10,
    total=Decimal(3000),
)

CHILD_APP_REPORT = Report(
    app_name="child",
    parent_app_name="parent",
    child_apps=[],
    child_apps_total=Decimal(0),
    date="2024-02",
    items=[
        ReportItem(
            name="service2",
            delta_value=Decimal(200),
            delta_percent=20,
            total=Decimal(2000),
        )
    ],
    items_total=Decimal(2000),
    items_delta_value=Decimal(200),
    items_delta_percent=20,
    total=Decimal(2000),
)


def test_aws_cost_report_get_reports(
    aws_cost_report_command: AwsCostReportCommand,
    mock_cost_management_api: Any,
) -> None:
    mocked_api = mock_cost_management_api.create_from_secret.return_value
    mocked_api.get_aws_costs_report.return_value = PARENT_APP_COST_RESPONSE

    reports = aws_cost_report_command.get_reports([PARENT_APP])

    assert reports == {
        "parent": PARENT_APP_COST_RESPONSE,
    }
    mocked_api.get_aws_costs_report.assert_called_once_with("parent")


def test_aws_cost_report_process_reports(
    aws_cost_report_command: AwsCostReportCommand,
) -> None:
    expected_reports = {
        "parent": PARENT_APP_REPORT,
        "child": CHILD_APP_REPORT,
    }

    reports = aws_cost_report_command.process_reports(
        [PARENT_APP, CHILD_APP],
        {
            "parent": PARENT_APP_COST_RESPONSE,
            "child": CHILD_APP_COST_RESPONSE,
        },
    )

    assert reports == expected_reports


def test_aws_cost_report_render(
    aws_cost_report_command: AwsCostReportCommand,
    fx: Callable,
) -> None:
    expected_output = fx("aws_cost_report.md")
    reports = {
        "parent": PARENT_APP_REPORT,
        "child": CHILD_APP_REPORT,
    }

    output = aws_cost_report_command.render(reports)

    assert output == expected_output
