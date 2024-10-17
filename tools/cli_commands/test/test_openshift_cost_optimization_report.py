from collections.abc import Callable
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.typed_queries.cost_report.app_names import App
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    CostNamespaceLabels,
)
from tools.cli_commands.cost_report.model import (
    OptimizationReport,
    OptimizationReportItem,
)
from tools.cli_commands.cost_report.openshift_cost_optimization import (
    OpenShiftCostOptimizationReportCommand,
)
from tools.cli_commands.test.conftest import (
    COST_REPORT_SECRET,
    OPENSHIFT_COST_OPTIMIZATION_RESPONSE,
    OPENSHIFT_COST_OPTIMIZATION_WITH_FUZZY_MATCH_RESPONSE,
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


@pytest.fixture
def openshift_cost_optimization_report_command(
    mock_gql: Any,
    mock_cost_management_api: Any,
    mock_fetch_cost_report_secret: Any,
) -> OpenShiftCostOptimizationReportCommand:
    return OpenShiftCostOptimizationReportCommand.create()


@pytest.fixture
def mock_get_app_names(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift_cost_optimization.get_app_names"
    )


@pytest.fixture
def mock_get_cost_namespaces(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.openshift_cost_optimization.get_cost_namespaces"
    )


APP = App(name="app", parent_app_name=None)

APP_NAMESPACE = CostNamespace(
    name="some-project",
    labels=CostNamespaceLabels(insights_cost_management_optimizations="true"),
    app_name=APP.name,
    cluster_name="some-cluster",
    cluster_external_id="some-cluster-uuid",
)

APP_NAMESPACE_OPTIMIZATION_DISABLED = CostNamespace(
    name="some-project-disabled",
    labels=CostNamespaceLabels(),
    app_name=APP.name,
    cluster_name="some-cluster",
    cluster_external_id="some-cluster-uuid",
)


def test_openshift_cost_optimization_report_execute(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
    mock_get_app_names: Any,
    mock_get_cost_namespaces: Any,
    fx: Callable,
) -> None:
    mock_get_app_names.return_value = []
    mock_get_cost_namespaces.return_value = []
    expected_output = fx("empty_openshift_cost_optimization_report.md")

    output = openshift_cost_optimization_report_command.execute()

    assert output.rstrip() == expected_output.rstrip()


def test_openshift_cost_optimization_report_get_apps(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
    mock_get_app_names: Any,
) -> None:
    expected_apps = [APP]
    mock_get_app_names.return_value = expected_apps

    apps = openshift_cost_optimization_report_command.get_apps()

    assert apps == expected_apps


def test_openshift_cost_optimization_report_get_cost_namespaces(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
    mock_get_cost_namespaces: Any,
) -> None:
    expected_namespaces = [APP_NAMESPACE]
    mock_get_cost_namespaces.return_value = [
        APP_NAMESPACE,
        APP_NAMESPACE_OPTIMIZATION_DISABLED,
    ]

    apps = openshift_cost_optimization_report_command.get_cost_namespaces()

    assert apps == expected_namespaces


def test_openshift_cost_optimization_report_get_cost_namespaces_filter(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
    mock_get_cost_namespaces: Any,
) -> None:
    expected_namespaces = [APP_NAMESPACE]
    mock_get_cost_namespaces.return_value = expected_namespaces

    apps = openshift_cost_optimization_report_command.get_cost_namespaces()

    assert apps == expected_namespaces


def test_openshift_cost_optimization_report_get_reports(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
    mock_cost_management_api: Any,
) -> None:
    mocked_api = mock_cost_management_api.create_from_secret.return_value
    mocked_api.get_openshift_cost_optimization_report.return_value = (
        OPENSHIFT_COST_OPTIMIZATION_RESPONSE
    )

    reports = openshift_cost_optimization_report_command.get_reports([APP_NAMESPACE])

    assert reports == {APP_NAMESPACE: OPENSHIFT_COST_OPTIMIZATION_RESPONSE}
    mocked_api.get_openshift_cost_optimization_report.assert_called_once_with(
        project=APP_NAMESPACE.name,
        cluster=APP_NAMESPACE.cluster_external_id,
    )


def test_openshift_cost_optimization_report_get_reports_with_fuzzy_results(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
    mock_cost_management_api: Any,
) -> None:
    mocked_api = mock_cost_management_api.create_from_secret.return_value
    mocked_api.get_openshift_cost_optimization_report.return_value = (
        OPENSHIFT_COST_OPTIMIZATION_WITH_FUZZY_MATCH_RESPONSE
    )

    reports = openshift_cost_optimization_report_command.get_reports([APP_NAMESPACE])

    assert reports == {APP_NAMESPACE: OPENSHIFT_COST_OPTIMIZATION_RESPONSE}
    mocked_api.get_openshift_cost_optimization_report.assert_called_once_with(
        project=APP_NAMESPACE.name,
        cluster=APP_NAMESPACE.cluster_external_id,
    )


APP_REPORT = OptimizationReport(
    app_name=APP.name,
    items=[
        OptimizationReportItem(
            cluster=APP_NAMESPACE.cluster_name,
            project=APP_NAMESPACE.name,
            workload="test-deployment",
            workload_type="deployment",
            container="test",
            current_cpu_limit="4",
            current_cpu_request="1",
            current_memory_limit="5Gi",
            current_memory_request="400Mi",
            recommend_cpu_request="3",
            recommend_cpu_limit="5",
            recommend_memory_request="700Mi",
            recommend_memory_limit="6Gi",
        )
    ],
)


def test_openshift_cost_report_process_reports(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
) -> None:
    expected_reports = [APP_REPORT]

    reports = openshift_cost_optimization_report_command.process_reports(
        apps=[APP],
        responses={
            APP_NAMESPACE: OPENSHIFT_COST_OPTIMIZATION_RESPONSE,
        },
    )

    assert reports == expected_reports


def test_openshift_cost_report_render(
    openshift_cost_optimization_report_command: OpenShiftCostOptimizationReportCommand,
    fx: Callable,
) -> None:
    expected_output = fx("openshift_cost_optimization_report.md")
    reports = [APP_REPORT]

    output = openshift_cost_optimization_report_command.render(reports)

    assert output == expected_output
