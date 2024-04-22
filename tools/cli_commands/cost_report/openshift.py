from typing import Self

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.cost_report.settings import get_cost_report_settings
from reconcile.utils import gql
from reconcile.utils.secret_reader import create_secret_reader
from tools.cli_commands.cost_report.cost_management_api import CostManagementApi


class OpenShiftCostReportCommand:
    def __init__(
        self,
        gql_api: gql.GqlApi,
        cost_management_api: CostManagementApi,
    ) -> None:
        self.gql_api = gql_api
        self.cost_management_api = cost_management_api

    def execute(self) -> str:
        return ""

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
