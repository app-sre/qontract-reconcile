from typing import Any, List, Self

from reconcile.utils.oauth2_backend_application_session import (
    OAuth2BackendApplicationSession,
)
from tools.cli_commands.cost_report.response import ReportCostResponse

REQUEST_TIMEOUT = 60


class CostManagementApi:
    def __init__(
        self,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: List[str] | None = None,
        request_timeout: int | None = REQUEST_TIMEOUT,
    ) -> None:
        self.base_url = base_url
        self.request_timeout = request_timeout
        self.session = OAuth2BackendApplicationSession(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
            scope=scope,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        self.session.close()

    def get_aws_costs_report(self, app: str) -> ReportCostResponse:
        params = {
            "cost_type": "calculated_amortized_cost",
            "delta": "cost",
            "filter[resolution]": "monthly",
            "filter[tag:app]": app,
            "filter[time_scope_units]": "month",
            "filter[time_scope_value]": "-2",
            "group_by[service]": "*",
        }
        response = self.session.request(
            method="GET",
            url=f"{self.base_url}/reports/aws/costs/",
            headers={"Content-Type": "application/json"},
            params=params,
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        return ReportCostResponse.parse_obj(response.json())
