from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Self

from sretoolbox.utils import threaded

from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    get_cost_namespaces,
)
from reconcile.utils import gql
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.model import (
    OptimizationReport,
    OptimizationReportItem,
)
from tools.cli_commands.cost_report.response import (
    OpenShiftCostOptimizationReportResponse,
    OpenShiftCostOptimizationResponse,
    ResourceConfigResponse,
)
from tools.cli_commands.cost_report.util import fetch_cost_report_secret
from tools.cli_commands.cost_report.view import (
    render_openshift_cost_optimization_report,
)

THREAD_POOL_SIZE = 10


class OpenShiftCostOptimizationReportCommand:
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
        cost_namespaces = get_cost_namespaces(self.gql_api)
        return [
            n
            for n in cost_namespaces
            if n.labels.insights_cost_management_optimizations == "true"
        ]

    def get_reports(
        self,
        cost_namespaces: Iterable[CostNamespace],
    ) -> dict[CostNamespace, OpenShiftCostOptimizationReportResponse]:
        results = threaded.run(self._get_report, cost_namespaces, self.thread_pool_size)
        return dict(results)

    def process_reports(
        self,
        apps: Iterable[App],
        responses: Mapping[CostNamespace, OpenShiftCostOptimizationReportResponse],
    ) -> list[OptimizationReport]:
        app_responses = defaultdict(list)
        for cost_namespace, response in responses.items():
            app_responses[cost_namespace.app_name].append(response)
        return [
            self._build_report(
                app.name,
                app_responses.get(app.name, []),
            )
            for app in apps
        ]

    def _get_report(
        self,
        cost_namespace: CostNamespace,
    ) -> tuple[CostNamespace, OpenShiftCostOptimizationReportResponse]:
        cluster = (
            cost_namespace.cluster_external_id
            if cost_namespace.cluster_external_id is not None
            else cost_namespace.cluster_name
        )
        response = self.cost_management_api.get_openshift_cost_optimization_report(
            project=cost_namespace.name,
            cluster=cluster,
        )
        response.data = [
            data
            for data in response.data
            if self._match_cost_namespace(data, cost_namespace)
        ]
        return cost_namespace, response

    @staticmethod
    def _match_cost_namespace(
        response: OpenShiftCostOptimizationResponse,
        cost_namespace: CostNamespace,
    ) -> bool:
        """
        Exactly match the cost namespace from the response data.
        Cost Management API returns fuzzy match on fields.
        Client side filter is needed.

        :param response: OpenShiftCostOptimizationResponse
        :param cost_namespace: CostNamespace
        :return: exactly match or not
        """
        if cluster_uuid := cost_namespace.cluster_external_id:
            if response.cluster_uuid != cluster_uuid:
                return False
        elif response.cluster_alias != cost_namespace.cluster_name:
            return False
        return response.project == cost_namespace.name

    @staticmethod
    def render(
        reports: Iterable[OptimizationReport],
    ) -> str:
        return render_openshift_cost_optimization_report(reports)

    def _build_report(
        self,
        app_name: str,
        responses: list[OpenShiftCostOptimizationReportResponse],
    ) -> OptimizationReport:
        return OptimizationReport(
            app_name=app_name,
            items=[self._build_report_item(data) for r in responses for data in r.data],
        )

    def _build_report_item(
        self,
        data: OpenShiftCostOptimizationResponse,
    ) -> OptimizationReportItem:
        current = data.recommendations.current
        terms = data.recommendations.recommendation_terms
        recommend = next(
            engine.cost.config
            for t in [terms.long_term, terms.medium_term, terms.short_term]
            if (engine := t.recommendation_engines) is not None
        )

        return OptimizationReportItem(
            cluster=data.cluster_alias,
            project=data.project,
            workload=data.workload,
            workload_type=data.workload_type,
            container=data.container,
            current_cpu_limit=self._build_resource_config(current.limits.cpu),
            current_cpu_request=self._build_resource_config(current.requests.cpu),
            current_memory_limit=self._build_resource_config(current.limits.memory),
            current_memory_request=self._build_resource_config(current.requests.memory),
            recommend_cpu_limit=self._build_resource_config(recommend.limits.cpu),
            recommend_cpu_request=self._build_resource_config(recommend.requests.cpu),
            recommend_memory_limit=self._build_resource_config(recommend.limits.memory),
            recommend_memory_request=self._build_resource_config(
                recommend.requests.memory
            ),
        )

    @staticmethod
    def _build_resource_config(response: ResourceConfigResponse) -> str | None:
        if response.amount is None:
            return None
        if response.format is None:
            return str(round(response.amount))
        return f"{round(response.amount)}{response.format}"

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
