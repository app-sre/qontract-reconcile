from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Self

from sretoolbox.utils import threaded

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.typed_queries.cost_report.settings import get_cost_report_settings
from reconcile.utils import gql
from reconcile.utils.secret_reader import create_secret_reader
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ReportItem
from tools.cli_commands.cost_report.response import ReportCostResponse
from tools.cli_commands.cost_report.util import process_reports
from tools.cli_commands.cost_report.view import render_aws_cost_report

THREAD_POOL_SIZE = 10


class AwsCostReportCommand:
    def __init__(
        self,
        gql_api: gql.GqlApi,
        cost_management_api: CostManagementApi,
        cost_management_console_base_url: str,
        thread_pool_size: int = THREAD_POOL_SIZE,
    ) -> None:
        self.gql_api = gql_api
        self.cost_management_api = cost_management_api
        self.cost_management_console_base_url = cost_management_console_base_url
        self.thread_pool_size = thread_pool_size

    def execute(self) -> str:
        apps = self.get_apps()
        responses = self.get_reports(apps)
        reports = self.process_reports(apps, responses)
        return self.render(reports)

    def get_apps(self) -> list[App]:
        """
        Get all apps from the gql API.
        """
        return get_app_names(self.gql_api)

    def _get_report(self, app: App) -> tuple[str, ReportCostResponse]:
        return app.name, self.cost_management_api.get_aws_costs_report(app.name)

    def get_reports(
        self,
        apps: Iterable[App],
    ) -> Mapping[str, ReportCostResponse]:
        """
        Fetch reports from cost management API
        """
        results = threaded.run(self._get_report, apps, self.thread_pool_size)
        return dict(results)

    def process_reports(
        self,
        apps: Iterable[App],
        responses: Mapping[str, ReportCostResponse],
    ) -> dict[str, Report]:
        """
        Build reports with parent-child app tree.
        """
        return process_reports(
            apps,
            responses,
            report_builder=self._build_report,
        )

    def render(self, reports: Mapping[str, Report]) -> str:
        return render_aws_cost_report(
            reports=reports,
            cost_management_console_base_url=self.cost_management_console_base_url,
        )

    @staticmethod
    def _build_report(
        app_name: str,
        parent_app_name: str | None,
        child_apps: list[str],
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

        items = [
            ReportItem(
                name=service.service,
                delta_value=value.delta_value,
                delta_percent=value.delta_percent,
                total=value.cost.total.value,
            )
            for data in response.data
            for service in data.services
            if len(service.values) == 1 and (value := service.values[0]) is not None
        ]

        items_total = response.meta.total.cost.total.value
        total = items_total + child_apps_total
        date = next((d for data in response.data if (d := data.date)), "")

        return Report(
            app_name=app_name,
            child_apps=child_app_reports,
            child_apps_total=child_apps_total,
            date=date,
            parent_app_name=parent_app_name,
            items_delta_value=response.meta.delta.value,
            items_delta_percent=response.meta.delta.percent,
            items_total=items_total,
            total=total,
            items=items,
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
            thread_pool_size=THREAD_POOL_SIZE,
        )
