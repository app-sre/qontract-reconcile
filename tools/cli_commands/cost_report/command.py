from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping
from decimal import Decimal
from typing import List, Self

from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.utils import gql
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.model import Report, ServiceReport
from tools.cli_commands.cost_report.response import ReportCostResponse


class CostReportCommand:
    def __init__(
        self,
        gql_api: gql.GqlApi,
        cost_management_api: CostManagementApi,
    ) -> None:
        self.gql_api = gql_api
        self.cost_management_api = cost_management_api

    def execute(self) -> str:
        apps = self.get_apps()
        reports = self.get_reports(apps)
        return self.render(reports)

    def get_apps(self) -> list[App]:
        """
        Get all apps from the gql API.
        """
        return get_app_names(self.gql_api)

    def get_reports(self, apps: Iterable[App]) -> dict[str, Report]:
        """
        Fetch reports from cost management API and build reports with parent-child app tree.
        """

        # TODO: Fetch reports concurrently
        responses = {
            app.name: self.cost_management_api.get_aws_costs_report(app.name)
            for app in apps
        }

        child_apps_by_parent = defaultdict(list)
        for app in apps:
            child_apps_by_parent[app.parent_app_name].append(app.name)

        reports = {}
        root_apps = child_apps_by_parent.get(None, [])
        for app in root_apps:
            self._dfs_reports(
                app,
                None,
                child_apps_by_parent=child_apps_by_parent,
                responses=responses,
                reports=reports,
            )
        return reports

    def render(self, reports: Mapping[str, Report]) -> str:
        return ""

    def _dfs_reports(
        self,
        app_name: str,
        parent_app_name: str | None,
        child_apps_by_parent: Mapping[str | None, list[str]],
        responses: Mapping[str, ReportCostResponse],
        reports: MutableMapping[str, Report],
    ) -> None:
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
            response=responses[app_name],
        )

    @staticmethod
    def _build_report(
        app_name: str,
        parent_app_name: str,
        child_apps: List[str],
        reports: Mapping[str, Report],
        response: ReportCostResponse,
    ) -> Report:
        child_apps_total = Decimal(
            sum(reports[child_app].total for child_app in child_apps)
        )
        services_total = response.meta.total.cost.total.value
        total = services_total + child_apps_total
        return Report(
            app_name=app_name,
            child_apps=child_apps,
            child_apps_total=child_apps_total,
            parent_app_name=parent_app_name,
            services_delta_value=response.meta.delta.value,
            services_delta_percentage=response.meta.delta.percent,
            services_total=services_total,
            total=total,
            services=[
                ServiceReport(
                    service=service.service,
                    delta_value=value.delta_value,
                    delta_percentage=value.delta_percent,
                    total=value.cost.total.value,
                )
                for data in response.data
                for service in data.services
                if len(service.values) == 1 and (value := service.values[0])
            ],
        )

    @classmethod
    def create(
        cls,
    ) -> Self:
        gql_api = gql.get_api()
        cost_management_api = CostManagementApi()
        return cls(
            gql_api=gql_api,
            cost_management_api=cost_management_api,
        )
