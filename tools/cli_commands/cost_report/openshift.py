from collections.abc import Iterable
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
from tools.cli_commands.cost_report.response import OpenShiftReportCostResponse

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
        report_responses = self.get_reports(cost_namespaces)
        return ""

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
