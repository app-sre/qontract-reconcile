from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Self

from sretoolbox.utils import threaded

from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    get_cost_namespaces,
)
from reconcile.utils import gql
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.model import ChildAppReport, Report, ReportItem
from tools.cli_commands.cost_report.response import OpenShiftReportCostResponse
from tools.cli_commands.cost_report.util import (
    fetch_cost_report_secret,
    process_reports,
)
from tools.cli_commands.cost_report.view import render_openshift_cost_report

THREAD_POOL_SIZE = 10


class OpenShiftCostReportCommand:
    def __init__(
        self,
        gql_api: gql.GqlApi,
        cost_management_api: CostManagementApi,
        thread_pool_size: int = THREAD_POOL_SIZE,
    ) -> None:
        self.gql_api = gql_api
        self.cost_management_api = cost_management_api
        self.thread_pool_size = thread_pool_size

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
    ) -> tuple[CostNamespace, OpenShiftReportCostResponse]:
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
        """
        Fetch reports from cost management API
        """
        results = threaded.run(self._get_report, cost_namespaces, self.thread_pool_size)
        return dict(results)

    def process_reports(
        self,
        apps: Iterable[App],
        responses: Mapping[CostNamespace, OpenShiftReportCostResponse],
    ) -> dict[str, Report]:
        """
        Build reports with parent-child app tree.
        """
        app_responses = defaultdict(list)
        for cost_namespace, response in responses.items():
            app_responses[cost_namespace.app_name].append(response)
        return process_reports(
            apps,
            app_responses,
            report_builder=self._build_report,
        )

    @staticmethod
    def render(
        reports: Mapping[str, Report],
    ) -> str:
        return render_openshift_cost_report(reports=reports)

    @staticmethod
    def _build_report(
        app_name: str,
        parent_app_name: str,
        child_apps: list[str],
        reports: Mapping[str, Report],
        response: list[OpenShiftReportCostResponse],
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
                name=f"{value.clusters[0]}/{project.project}",
                delta_value=value.delta_value,
                delta_percent=value.delta_percent,
                total=value.cost.total.value,
            )
            for r in response
            for data in r.data
            for project in data.projects
            if len(project.values) == 1 and (value := project.values[0]) is not None
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
            (d for r in response for data in r.data if (d := data.date)),
            "",
        )

        return Report(
            app_name=app_name,
            child_apps=child_app_reports,
            child_apps_total=child_apps_total,
            date=date,
            parent_app_name=parent_app_name,
            items_delta_value=items_delta_value,
            items_delta_percent=items_delta_percent,
            items_total=items_total,
            total=total,
            items=items,
        )

    @classmethod
    def create(cls) -> Self:
        gql_api = gql.get_api()
        secret = fetch_cost_report_secret(gql_api)
        cost_management_api = CostManagementApi.create_from_secret(secret)
        return cls(
            gql_api=gql_api,
            cost_management_api=cost_management_api,
            thread_pool_size=THREAD_POOL_SIZE,
        )
