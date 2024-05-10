from urllib3.util import Retry

from reconcile.utils.oauth2_backend_application_session import (
    OAuth2BackendApplicationSession,
)
from reconcile.utils.rest_api_base import ApiBase
from tools.cli_commands.cost_report.response import (
    OpenShiftReportCostResponse,
    ReportCostResponse,
)

REQUEST_TIMEOUT = 60


class CostManagementApi(ApiBase):
    def __init__(
        self,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: list[str] | None = None,
    ) -> None:
        session = OAuth2BackendApplicationSession(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
            scope=scope,
        )
        max_retries = Retry(
            total=3,
            backoff_factor=15,  # large backoff required for server-side processing
            status_forcelist=[500, 502, 503, 504],
        )
        super().__init__(
            host=base_url,
            session=session,
            read_timeout=REQUEST_TIMEOUT,
            max_retries=max_retries,
        )

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
            url=f"{self.host}/reports/aws/costs/",
            params=params,
            timeout=self.read_timeout,
        )
        response.raise_for_status()
        return ReportCostResponse.parse_obj(response.json())

    def get_openshift_costs_report(
        self,
        cluster: str,
        project: str,
    ) -> OpenShiftReportCostResponse:
        params = {
            "delta": "cost",
            "filter[resolution]": "monthly",
            "filter[cluster]": cluster,
            "filter[exact:project]": project,
            "filter[time_scope_units]": "month",
            "filter[time_scope_value]": "-2",
            "group_by[project]": "*",
        }
        response = self.session.request(
            method="GET",
            url=f"{self.host}/reports/openshift/costs/",
            params=params,
            timeout=self.read_timeout,
        )
        response.raise_for_status()
        return OpenShiftReportCostResponse.parse_obj(response.json())
