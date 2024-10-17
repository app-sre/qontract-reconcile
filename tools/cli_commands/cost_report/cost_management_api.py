from collections.abc import Mapping
from typing import Self
from urllib.parse import urljoin, urlparse

from requests import Response
from urllib3.util import Retry

from reconcile.utils.oauth2_backend_application_session import (
    OAuth2BackendApplicationSession,
)
from reconcile.utils.rest_api_base import ApiBase
from tools.cli_commands.cost_report.response import (
    AwsReportCostResponse,
    OpenShiftCostOptimizationReportResponse,
    OpenShiftReportCostResponse,
)

REQUEST_TIMEOUT = 60
PAGE_LIMIT = 100
MEMORY_UNIT = "MiB"
CPU_UNIT = "millicores"


class CostManagementApi(ApiBase):
    """
    Cost Management API client.

    Doc at https://console.redhat.com/docs/api/cost-management
    """

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
        self.base_url = base_url
        parsed_url = urlparse(base_url)
        host = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        super().__init__(
            host=host,
            session=session,
            read_timeout=REQUEST_TIMEOUT,
            max_retries=max_retries,
        )

    def get_aws_costs_report(self, app: str) -> AwsReportCostResponse:
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
            params=params,
            timeout=self.read_timeout,
        )
        response.raise_for_status()
        return AwsReportCostResponse.parse_obj(response.json())

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
            url=f"{self.base_url}/reports/openshift/costs/",
            params=params,
            timeout=self.read_timeout,
        )
        response.raise_for_status()
        return OpenShiftReportCostResponse.parse_obj(response.json())

    def get_openshift_cost_optimization_report(
        self,
        cluster: str,
        project: str,
    ) -> OpenShiftCostOptimizationReportResponse:
        params = {
            "cluster": cluster,
            "project": project,
            "limit": str(PAGE_LIMIT),
            "memory-unit": MEMORY_UNIT,
            "cpu-unit": CPU_UNIT,
        }
        response = self.session.request(
            method="GET",
            url=f"{self.base_url}/recommendations/openshift",
            params=params,
            timeout=self.read_timeout,
        )
        response.raise_for_status()

        data = self._get_paginated(response)
        return OpenShiftCostOptimizationReportResponse.parse_obj(data)

    def _get_paginated(
        self,
        response: Response,
    ) -> dict[str, list]:
        body = response.json()
        data = body.get("data", [])

        while next_url := body.get("links", {}).get("next"):
            r = self.session.request(
                method="GET",
                url=urljoin(self.host, next_url),
                timeout=self.read_timeout,
            )
            r.raise_for_status()
            body = r.json()
            data.extend(body.get("data", []))

        return {"data": data}

    @classmethod
    def create_from_secret(
        cls,
        secret: Mapping[str, str],
    ) -> Self:
        return cls(
            base_url=secret["api_base_url"],
            token_url=secret["token_url"],
            client_id=secret["client_id"],
            client_secret=secret["client_secret"],
            scope=secret["scope"].split(" "),
        )
