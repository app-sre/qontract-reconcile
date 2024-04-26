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
from reconcile.typed_queries.cost_report.cost_namespaces import CostNamespace
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ServiceReport
from tools.cli_commands.cost_report.openshift import OpenShiftCostReportCommand
from tools.cli_commands.cost_report.response import OpenShiftReportCostResponse


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


def test_openshift_cost_report_create(
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
    app_name=PARENT_APP.name,
    cluster_name="parent_cluster",
    cluster_external_id="parent_cluster_external_id",
)
CHILD_APP_NAMESPACE = CostNamespace(
    name="child_namespace",
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
    mock_cost_management_api.return_value.get_openshift_costs_report.return_value = (
        PARENT_APP_COST_RESPONSE
    )

    reports = openshift_cost_report_command.get_reports([PARENT_APP_NAMESPACE])

    assert reports == {PARENT_APP_NAMESPACE: PARENT_APP_COST_RESPONSE}
    mock_cost_management_api.return_value.get_openshift_costs_report.assert_called_once_with(
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
    services=[
        ServiceReport(
            service=f"{PARENT_APP_NAMESPACE.cluster_name}/{PARENT_APP_NAMESPACE.name}",
            delta_value=Decimal(100),
            delta_percent=10,
            total=Decimal(1100),
        )
    ],
    services_total=Decimal(1100),
    services_delta_value=Decimal(100),
    services_delta_percent=10,
    total=Decimal(3300),
)

CHILD_APP_REPORT = Report(
    app_name="child",
    parent_app_name="parent",
    child_apps=[],
    child_apps_total=Decimal(0),
    date="2024-02",
    services=[
        ServiceReport(
            service=f"{CHILD_APP_NAMESPACE.cluster_name}/{CHILD_APP_NAMESPACE.name}",
            delta_value=Decimal(200),
            delta_percent=10,
            total=Decimal(2200),
        )
    ],
    services_total=Decimal(2200),
    services_delta_value=Decimal(200),
    services_delta_percent=10,
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
