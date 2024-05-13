from typing import Self

from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    get_cost_namespaces,
)
from reconcile.utils import gql
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.util import fetch_cost_report_secret

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
        return ""

    def get_apps(self) -> list[App]:
        return get_app_names(self.gql_api)

    def get_cost_namespaces(self) -> list[CostNamespace]:
        return get_cost_namespaces(self.gql_api)

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
