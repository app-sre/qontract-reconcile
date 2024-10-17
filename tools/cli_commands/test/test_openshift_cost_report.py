from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.typed_queries.cost_report.app_names import App
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    CostNamespaceLabels,
)
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ReportItem
from tools.cli_commands.cost_report.openshift import OpenShiftCostReportCommand
from tools.cli_commands.cost_report.response import OpenShiftReportCostResponse
from tools.cli_commands.test.conftest import (
    COST_REPORT_SECRET,
)


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.openshift.gql")


@pytest.fixture
def mock_cost_management_api(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift.CostManagementApi",
        autospec=True,
    )


@pytest.fixture
def mock_fetch_cost_report_secret(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift.fetch_cost_report_secret",
        return_value=COST_REPORT_SECRET,
    )


def test_openshift_cost_report_create(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_fetch_cost_report_secret: Any,
) -> None:
    openshift_cost_report_command = OpenShiftCostReportCommand.create()

    assert isinstance(openshift_cost_report_command, OpenShiftCostReportCommand)
    assert openshift_cost_report_command.gql_api == mock_gql.get_api.return_value
    assert (
        openshift_cost_report_command.cost_management_api
        == mock_cost_management_api.create_from_secret.return_value
    )
    assert openshift_cost_report_command.thread_pool_size == 10
    mock_cost_management_api.create_from_secret.assert_called_once_with(
        COST_REPORT_SECRET
    )
    mock_fetch_cost_report_secret.assert_called_once_with(mock_gql.get_api.return_value)


@pytest.fixture
def openshift_cost_report_command(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_fetch_cost_report_secret: Any,
) -> OpenShiftCostReportCommand:
    return OpenShiftCostReportCommand.create()


@pytest.fixture
def mock_get_app_names(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.openshift.get_app_names")


@pytest.fixture
def mock_get_cost_namespaces(mocker: MockerFixture) -> Any:
    return mocker.patch("tools.cli_commands.cost_report.openshift.get_cost_namespaces")


PARENT_APP = App(name="parent", parent_app_name=None)
CHILD_APP = App(name="child", parent_app_name="parent")

PARENT_APP_NAMESPACE = CostNamespace(
    name="parent_namespace",
    labels=CostNamespaceLabels(),
    app_name=PARENT_APP.name,
    cluster_name="parent_cluster",
    cluster_external_id="parent_cluster_external_id",
)
CHILD_APP_NAMESPACE = CostNamespace(
    name="child_namespace",
    labels=CostNamespaceLabels(),
    app_name=CHILD_APP.name,
    cluster_name="child_cluster",
    cluster_external_id="child_cluster_external_id",
)


def test_openshift_cost_report_execute(
    openshift_cost_report_command: OpenShiftCostReportCommand,
    mock_get_app_names: Any,
    mock_get_cost_namespaces: Any,
    fx: Callable,
) -> None:
    expected_output = fx("empty_openshift_cost_report.md")

    mock_get_app_names.return_value = []
    mock_get_cost_namespaces.return_value = []

    output = openshift_cost_report_command.execute()

    assert output.rstrip() == expected_output.rstrip()


def test_openshift_cost_report_get_apps(
    openshift_cost_report_command: OpenShiftCostReportCommand,
    mock_get_app_names: Any,
) -> None:
    expected_apps = [PARENT_APP, CHILD_APP]
    mock_get_app_names.return_value = expected_apps

    apps = openshift_cost_report_command.get_apps()

    assert apps == expected_apps


def test_openshift_cost_report_get_cost_namespaces(
    openshift_cost_report_command: OpenShiftCostReportCommand,
    mock_get_cost_namespaces: Any,
) -> None:
    expected_namespaces = [PARENT_APP_NAMESPACE, CHILD_APP_NAMESPACE]
    mock_get_cost_namespaces.return_value = expected_namespaces

    apps = openshift_cost_report_command.get_cost_namespaces()

    assert apps == expected_namespaces


def openshift_report_cost_response_builder(
    delta_value: int,
    delta_percent: int,
    total: int,
    project: str,
    cluster: str,
) -> OpenShiftReportCostResponse:
    return OpenShiftReportCostResponse.parse_obj({
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
                "projects": [
                    {
                        "project": project,
                        "values": [
                            {
                                "delta_value": delta_value,
                                "delta_percent": delta_percent,
                                "clusters": [cluster],
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


PARENT_APP_COST_RESPONSE = openshift_report_cost_response_builder(
    delta_value=100,
    delta_percent=10,
    total=1100,
    project=PARENT_APP_NAMESPACE.name,
    cluster=PARENT_APP_NAMESPACE.cluster_name,
)

CHILD_APP_COST_RESPONSE = openshift_report_cost_response_builder(
    delta_value=200,
    delta_percent=10,
    total=2200,
    project=CHILD_APP_NAMESPACE.name,
    cluster=CHILD_APP_NAMESPACE.cluster_name,
)


def test_openshift_cost_report_get_reports(
    openshift_cost_report_command: OpenShiftCostReportCommand,
    mock_cost_management_api: Any,
) -> None:
    mocked_api = mock_cost_management_api.create_from_secret.return_value
    mocked_api.get_openshift_costs_report.return_value = PARENT_APP_COST_RESPONSE

    reports = openshift_cost_report_command.get_reports([PARENT_APP_NAMESPACE])

    assert reports == {PARENT_APP_NAMESPACE: PARENT_APP_COST_RESPONSE}
    mocked_api.get_openshift_costs_report.assert_called_once_with(
        project=PARENT_APP_NAMESPACE.name,
        cluster=PARENT_APP_NAMESPACE.cluster_external_id,
    )


PARENT_APP_REPORT = Report(
    app_name="parent",
    parent_app_name=None,
    child_apps=[
        ChildAppReport(name="child", total=Decimal(2200)),
    ],
    child_apps_total=Decimal(2200),
    date="2024-02",
    items=[
        ReportItem(
            name=f"{PARENT_APP_NAMESPACE.cluster_name}/{PARENT_APP_NAMESPACE.name}",
            delta_value=Decimal(100),
            delta_percent=10,
            total=Decimal(1100),
        )
    ],
    items_total=Decimal(1100),
    items_delta_value=Decimal(100),
    items_delta_percent=10,
    total=Decimal(3300),
)

CHILD_APP_REPORT = Report(
    app_name="child",
    parent_app_name="parent",
    child_apps=[],
    child_apps_total=Decimal(0),
    date="2024-02",
    items=[
        ReportItem(
            name=f"{CHILD_APP_NAMESPACE.cluster_name}/{CHILD_APP_NAMESPACE.name}",
            delta_value=Decimal(200),
            delta_percent=10,
            total=Decimal(2200),
        )
    ],
    items_total=Decimal(2200),
    items_delta_value=Decimal(200),
    items_delta_percent=10,
    total=Decimal(2200),
)


def test_openshift_cost_report_process_reports(
    openshift_cost_report_command: OpenShiftCostReportCommand,
) -> None:
    expected_reports = {
        "parent": PARENT_APP_REPORT,
        "child": CHILD_APP_REPORT,
    }

    reports = openshift_cost_report_command.process_reports(
        apps=[PARENT_APP, CHILD_APP],
        responses={
            PARENT_APP_NAMESPACE: PARENT_APP_COST_RESPONSE,
            CHILD_APP_NAMESPACE: CHILD_APP_COST_RESPONSE,
        },
    )

    assert reports == expected_reports


def test_openshift_cost_report_render(
    openshift_cost_report_command: OpenShiftCostReportCommand,
    fx: Callable,
) -> None:
    expected_output = fx("openshift_cost_report.md")
    reports = {
        "parent": PARENT_APP_REPORT,
        "child": CHILD_APP_REPORT,
    }

    output = openshift_cost_report_command.render(reports)

    assert output == expected_output
