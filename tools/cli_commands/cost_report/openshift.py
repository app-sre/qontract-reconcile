from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping
from decimal import Decimal
from typing import Self, Tuple

from sretoolbox.utils import threaded

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    get_cost_namespaces,
)
from reconcile.typed_queries.cost_report.settings import get_cost_report_settings
from reconcile.utils import gql
from reconcile.utils.secret_reader import create_secret_reader
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ServiceReport
from tools.cli_commands.cost_report.response import OpenShiftReportCostResponse
from tools.cli_commands.cost_report.view import render_openshift_cost_report

THREAD_POOL_SIZE = 10


class OpenShiftCostReportCommand:
    def __init__(
        self,
        gql_api: gql.GqlApi,
        cost_management_api: CostManagementApi,
    ) -> None:
        self.gql_api = gql_api
        self.cost_management_api = cost_management_api

    def execute(self) -> str:
        apps = self.get_apps()
        cost_namespaces = self.get_cost_namespaces()
        responses = self.get_reports(cost_namespaces)
        reports = self.process_reports(apps, responses)
        return self.render(reports)

    def get_apps(self) -> list[App]:
        return get_app_names(self.gql_api)

    def get_cost_namespaces(self) -> list[CostNamespace]:
        return get_cost_namespaces(self.gql_api)

    def _get_report(
        self,
        cost_namespace: CostNamespace,
    ) -> Tuple[CostNamespace, OpenShiftReportCostResponse]:
        cluster = (
            cost_namespace.cluster_external_id
            if cost_namespace.cluster_external_id is not None
            else cost_namespace.cluster_name
        )
        response = self.cost_management_api.get_openshift_costs_report(
            project=cost_namespace.name,
            cluster=cluster,
        )
        return cost_namespace, response

    def get_reports(
        self,
        cost_namespaces: Iterable[CostNamespace],
    ) -> dict[CostNamespace, OpenShiftReportCostResponse]:
        results = threaded.run(self._get_report, cost_namespaces, THREAD_POOL_SIZE)
        return dict(results)

    def process_reports(
        self,
        apps: Iterable[App],
        responses: Mapping[CostNamespace, OpenShiftReportCostResponse],
    ) -> dict[str, Report]:
        app_responses = defaultdict(list)
        for cost_namespace, response in responses.items():
            app_responses[cost_namespace.app_name].append(response)

        child_apps_by_parent = defaultdict(list)
        for app in apps:
            child_apps_by_parent[app.parent_app_name].append(app.name)

        reports: dict[str, Report] = {}
        root_apps = child_apps_by_parent.get(None, [])
        for app_name in root_apps:
            self._dfs_reports(
                app_name,
                None,
                child_apps_by_parent=child_apps_by_parent,
                responses=app_responses,
                reports=reports,
            )
        return reports

    @staticmethod
    def render(reports):
        return render_openshift_cost_report(reports=reports)

    def _dfs_reports(
        self,
        app_name: str,
        parent_app_name: str | None,
        child_apps_by_parent: Mapping[str | None, list[str]],
        responses: Mapping[str, list[OpenShiftReportCostResponse]],
        reports: MutableMapping[str, Report],
    ):
        """
        Depth-first search to build the reports. Build leaf nodes first to ensure total is calculated correctly.
        """
        child_apps = child_apps_by_parent.get(app_name, [])
        for child_app in child_apps:
            self._dfs_reports(
                app_name=child_app,
                parent_app_name=app_name,
                child_apps_by_parent=child_apps_by_parent,
                responses=responses,
                reports=reports,
            )
        reports[app_name] = self._build_report(
            app_name=app_name,
            parent_app_name=parent_app_name,
            child_apps=child_apps,
            reports=reports,
            responses=responses[app_name],
        )

    @staticmethod
    def _build_report(
        app_name: str,
        parent_app_name: str,
        child_apps: list[str],
        reports: Mapping[str, Report],
        responses: list[OpenShiftReportCostResponse],
    ) -> Report:
        child_app_reports = [
            ChildAppReport(
                name=child_app,
                total=reports[child_app].total,
            )
            for child_app in child_apps
        ]
        child_apps_total = Decimal(
            sum(child_app.total for child_app in child_app_reports)
        )

        items = [
            ServiceReport(
                service=f"{cluster}/{project.project}",
                delta_value=value.delta_value,
                delta_percent=value.delta_percent,
                total=value.cost.total.value,
            )
            for response in responses
            for data in response.data
            for project in data.projects
            if len(project.values) == 1
            and (value := project.values[0]) is not None
            and len(value.clusters) == 1
            and (cluster := value.clusters[0]) is not None
        ]

        items_total = Decimal(sum(item.total for item in items))
        items_delta_value = Decimal(sum(item.delta_value for item in items))
        previous_items_total = items_total - items_delta_value
        items_delta_percent = (
            items_delta_value / previous_items_total * 100
            if previous_items_total != 0
            else None
        )
        total = items_total + child_apps_total

        date = next(
            (d for response in responses for data in response.data if (d := data.date)),
            "",
        )

        return Report(
            app_name=app_name,
            child_apps=child_app_reports,
            child_apps_total=child_apps_total,
            date=date,
            parent_app_name=parent_app_name,
            services_delta_value=items_delta_value,
            services_delta_percent=items_delta_percent,
            services_total=items_total,
            total=total,
            services=items,
        )

    @classmethod
    def create(
        cls,
    ) -> Self:
        gql_api = gql.get_api()
        vault_settings = get_app_interface_vault_settings(gql_api.query)
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        cost_report_settings = get_cost_report_settings(gql_api)
        secret = secret_reader.read_all_secret(cost_report_settings.credentials)
        cost_management_api = CostManagementApi(
            base_url=secret["api_base_url"],
            token_url=secret["token_url"],
            client_id=secret["client_id"],
            client_secret=secret["client_secret"],
            scope=secret["scope"].split(" "),
        )
        return cls(
            gql_api=gql_api,
            cost_management_api=cost_management_api,
        )
