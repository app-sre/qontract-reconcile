from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.typed_queries.cost_report.app_names import App
from tools.cli_commands.cost_report import CostReportCommand, Report


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.gql")


def test_cost_report_create(mock_gql: Any) -> None:
    cost_report_command = CostReportCommand.create()

    assert isinstance(cost_report_command, CostReportCommand)
    assert cost_report_command.gql_api == mock_gql.get_api.return_value


@pytest.fixture
def cost_report_command(mock_gql: Any) -> CostReportCommand:
    return CostReportCommand.create()


@pytest.fixture
def mock_get_app_names(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.get_app_names")


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


def test_cost_report_get_report(cost_report_command: CostReportCommand) -> None:
    assert cost_report_command.get_report([]) == Report()


def test_cost_report_render(cost_report_command: CostReportCommand) -> None:
    assert cost_report_command.render(Report()) == ""
