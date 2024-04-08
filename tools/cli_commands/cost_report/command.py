from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping
from decimal import Decimal
from typing import List, Self, Tuple

from sretoolbox.utils import threaded

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.typed_queries.cost_report.settings import get_cost_report_settings
from reconcile.utils import gql
from reconcile.utils.secret_reader import create_secret_reader
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ServiceReport
from tools.cli_commands.cost_report.response import ReportCostResponse
from tools.cli_commands.cost_report.view import render_report

THREAD_POOL_SIZE = 10


class CostReportCommand:
    def __init__(
        self,
        gql_api: gql.GqlApi,
        cost_management_api: CostManagementApi,
        cost_management_console_base_url: str,
    ) -> None:
        self.gql_api = gql_api
        self.cost_management_api = cost_management_api
        self.cost_management_console_base_url = cost_management_console_base_url

    def execute(self) -> str:
        apps = self.get_apps()
        reports = self.get_reports(apps)
        return self.render(reports)

    def get_apps(self) -> list[App]:
        """
        Get all apps from the gql API.
        """
        return get_app_names(self.gql_api)

    def _fetch_report(self, app: App) -> Tuple[str, ReportCostResponse]:
        return app.name, self.cost_management_api.get_aws_costs_report(app.name)

    def _fetch_reports(self, apps: Iterable[App]) -> dict[str, ReportCostResponse]:
        results = threaded.run(self._fetch_report, apps, THREAD_POOL_SIZE)
        return dict(results)

    def get_reports(self, apps: Iterable[App]) -> dict[str, Report]:
        """
        Fetch reports from cost management API and build reports with parent-child app tree.
        """
        responses = self._fetch_reports(apps)

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
                responses=responses,
                reports=reports,
            )
        return reports

    def render(self, reports: Mapping[str, Report]) -> str:
        return render_report(
            reports=reports,
            cost_management_console_base_url=self.cost_management_console_base_url,
        )

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
        parent_app_name: str | None,
        child_apps: List[str],
        reports: Mapping[str, Report],
        response: ReportCostResponse,
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
        services_total = response.meta.total.cost.total.value
        total = services_total + child_apps_total
        date = next((d for data in response.data if (d := data.date)), "")
        return Report(
            app_name=app_name,
            child_apps=child_app_reports,
            child_apps_total=child_apps_total,
            date=date,
            parent_app_name=parent_app_name,
            services_delta_value=response.meta.delta.value,
            services_delta_percent=response.meta.delta.percent,
            services_total=services_total,
            total=total,
            services=[
                ServiceReport(
                    service=service.service,
                    delta_value=value.delta_value,
                    delta_percent=value.delta_percent,
                    total=value.cost.total.value,
                )
                for data in response.data
                for service in data.services
                if len(service.values) == 1 and (value := service.values[0]) is not None
            ],
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
            cost_management_console_base_url=secret["console_base_url"],
        )
