from typing import Any

import pytest
from pytest_mock import MockerFixture

from tools.cli_commands.cost_report.openshift_cost_optimization import (
    OpenShiftCostOptimizationReportCommand,
)
from tools.cli_commands.test.conftest import (
    COST_REPORT_SECRET,
)


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift_cost_optimization.gql"
    )


@pytest.fixture
def mock_cost_management_api(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift_cost_optimization.CostManagementApi",
        autospec=True,
    )


@pytest.fixture
def mock_fetch_cost_report_secret(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift_cost_optimization.fetch_cost_report_secret",
        return_value=COST_REPORT_SECRET,
    )


def test_openshift_cost_optimization_report_create(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_fetch_cost_report_secret: Any,
) -> None:
    openshift_cost_optimization_report_command = (
        OpenShiftCostOptimizationReportCommand.create()
    )

    assert isinstance(
        openshift_cost_optimization_report_command,
        OpenShiftCostOptimizationReportCommand,
    )
    assert (
        openshift_cost_optimization_report_command.gql_api
        == mock_gql.get_api.return_value
    )
    assert (
        openshift_cost_optimization_report_command.cost_management_api
        == mock_cost_management_api.create_from_secret.return_value
    )
    assert openshift_cost_optimization_report_command.thread_pool_size == 10
    mock_cost_management_api.create_from_secret.assert_called_once_with(
        COST_REPORT_SECRET
    )
    mock_fetch_cost_report_secret.assert_called_once_with(mock_gql.get_api.return_value)
