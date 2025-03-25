from dataclasses import dataclass
from math import isnan
from typing import Any
from urllib.parse import urljoin

import jinja2
import requests

from reconcile.gql_definitions.fragments.saas_slo_document import (
    SLODocumentSLOV1,
)

PROM_QUERY_URL = "api/v1/query"
PROM_TIMEOUT = (5, 300)


@dataclass
class PromCredentials:
    prom_url: str
    is_basic_auth: bool
    prom_token: str


class EmptySLOResult(Exception):
    pass


class EmptySLOValue(Exception):
    pass


class InvalidSLOValue(Exception):
    pass


class SLODetails:
    def __init__(
        self,
        namespace_name: str,
        slo_document_name: str,
        cluster_name: str,
        prom_credentials: PromCredentials,
        slo: SLODocumentSLOV1,
    ):
        self.namespace_name = namespace_name
        self.slo_document_name = slo_document_name
        self.cluster_name = cluster_name
        self.prom_credentials = prom_credentials
        self.slo = slo

    def parse_prom_response(self, data: Any) -> float:
        result = data["data"]["result"]
        if not result:
            raise EmptySLOResult(
                f"prometheus returned empty result for SLO: {self.slo.name} of SLO document: {self.slo_document_name}"
            )
        slo_value = result[0]["value"]
        if not slo_value:
            raise EmptySLOValue(
                f"prometheus returned empty SLO value for SLO: {self.slo.name} of SLO document: {self.slo_document_name}"
            )
        slo_value = float(slo_value[1])
        if isnan(slo_value):
            raise InvalidSLOValue(
                f"invalid format for SLO: {self.slo.name} of SLO document: {self.slo_document_name}"
            )
        return slo_value

    def get_SLO_value(self) -> float:
        full_prom_url = urljoin((f"{self.prom_credentials.prom_url}"), PROM_QUERY_URL)
        headers = {
            "accept": "application/json",
        }
        headers["Authorization"] = (
            f"{'Basic' if self.prom_credentials.is_basic_auth else 'Bearer'} {self.prom_credentials.prom_token}"
        )
        template = jinja2.Template(self.slo.expr)
        prom_query = template.render({"window": self.slo.slo_parameters.window})
        response = requests.get(
            full_prom_url,
            params={"query": (f"{prom_query}")},
            headers=headers,
            timeout=PROM_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        slo_value = self.parse_prom_response(data)
        return slo_value
