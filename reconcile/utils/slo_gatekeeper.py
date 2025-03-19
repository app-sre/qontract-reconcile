import logging
from base64 import b64encode
from math import isnan
from typing import Any
from urllib.parse import urljoin

import jinja2
import requests
from pydantic import BaseModel

from reconcile.gql_definitions.fragments.saas_slo_document import (
    SaasSLODocument,
    SLODocumentSLOV1,
    SLONamespacesV1,
)
from reconcile.utils.secret_reader import SecretReaderBase

PROM_QUERY_URL = "api/v1/query"
PROM_TIMEOUT = (5, 300)


class SLODetails(BaseModel):
    def __init__(
        self,
        namespace_name: str,
        slo_document_name: str,
        cluster_name: str,
        prom_url: str,
        is_basic_auth: bool,
        prom_token: str,
        slo: SLODocumentSLOV1,
    ):
        self.namespace_name = namespace_name
        self.slo_document_name = slo_document_name
        self.cluster_name = cluster_name
        self.prom_url = prom_url
        self.prom_token = prom_token
        self.is_basic_auth = is_basic_auth
        self.slo = slo

    def parse_prom_response(self, data: Any) -> float:
        result = data["data"]["result"]
        if not result:
            raise Exception("prometheus returned empty result")
        slo_value = result[0]["value"]
        if not slo_value:
            raise Exception("prometheus returned empty SLO value")
        slo_value = float(slo_value[1])
        if isnan(slo_value):
            raise Exception("SLO value is having improper format")
        return slo_value

    def get_SLO_value(self) -> float:
        full_prom_url = urljoin((f"{self.prom_url}"), PROM_QUERY_URL)
        headers = {
            "accept": "application/json",
        }
        headers["Authorization"] = (
            f"{'Basic' if self.is_basic_auth else 'Bearer'} {self.prom_token}"
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


class SLOGateKeeper:
    def __init__(
        self, slo_documents: list[SaasSLODocument], secret_reader: SecretReaderBase
    ):
        self.secret_reader = secret_reader
        self.slo_details_list = self._create_SLO_details_list(slo_documents)

    def _create_SLO_details_list(
        self, slo_documents: list[SaasSLODocument]
    ) -> list[SLODetails]:
        slo_details_list = [
            SLODetails(
                namespace_name=namespace.namespace.name,
                cluster_name=namespace.namespace.cluster.name,
                slo_document_name=slo_document.name,
                prom_token=prom_token,
                prom_url=prom_url,
                is_basic_auth=is_basic_auth,
                slo=slo,
            )
            for slo_document in slo_documents
            for namespace in slo_document.namespaces
            if not namespace.slo_namespace or namespace.prometheus_access
            for prom_url, prom_token, is_basic_auth in [
                self._get_credentials_from_slo_namespace(namespace)
            ]
            for slo in slo_document.slos or []
        ]
        return slo_details_list

    def _get_credentials_from_slo_namespace(
        self, namespace: SLONamespacesV1
    ) -> tuple[str, str, bool]:
        prom_url: str = ""
        prom_token: str = ""
        is_basic_auth: bool = False
        if namespace.prometheus_access:
            if (
                namespace.prometheus_access.username
                and namespace.prometheus_access.password
            ):
                is_basic_auth = True
                username = self.secret_reader.read_secret(
                    namespace.prometheus_access.username
                )
                password = self.secret_reader.read_secret(
                    namespace.prometheus_access.password
                )
                prom_token = b64encode(f"{username}:{password}".encode()).decode(
                    "utf-8"
                )
                prom_url = namespace.prometheus_access.url
        else:
            prom_url = namespace.namespace.cluster.prometheus_url
            if not namespace.namespace.cluster.automation_token:
                raise Exception(
                    f"cluster {namespace.namespace.cluster.name} does not have automation token set"
                )
            prom_token = self.secret_reader.read_secret(
                namespace.namespace.cluster.automation_token
            )
        return (prom_url, prom_token, is_basic_auth)

    def is_slo_breached(self) -> bool:
        for slo in self.slo_details_list:
            slo_value = slo.get_SLO_value()
            if slo_value < slo.slo.slo_target:
                logging.info(
                    f"SLO {slo.slo.name} from document {slo.slo_document_name} is breached. Expected value:{slo.slo.slo_target} current value:{slo_value}"
                )
                return True
        return False
