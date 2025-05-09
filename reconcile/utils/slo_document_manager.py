import itertools
import logging
from dataclasses import dataclass
from math import isnan
from typing import Any, Self

import jinja2
import requests
from sretoolbox.utils import threaded

from reconcile.gql_definitions.fragments.saas_slo_document import (
    SLODocument,
    SLODocumentSLOV1,
    SLOExternalPrometheusAccessV1,
    SLONamespacesV1,
)
from reconcile.utils.rest_api_base import ApiBase, BearerTokenAuth
from reconcile.utils.secret_reader import SecretReaderBase

PROM_QUERY_URL = "api/v1/query"

DEFAULT_READ_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_THREAD_POOL_SIZE = 10


class EmptySLOResult(Exception):
    pass


class EmptySLOValue(Exception):
    pass


class InvalidSLOValue(Exception):
    pass


@dataclass
class SLODetails:
    namespace_name: str
    slo_document_name: str
    cluster_name: str
    slo: SLODocumentSLOV1
    service_name: str
    current_slo_value: float


@dataclass
class NamespaceSLODocument:
    name: str
    namespace: SLONamespacesV1
    slos: list[SLODocumentSLOV1] | None

    def get_host_url(self) -> str:
        return (
            self.namespace.prometheus_access.url
            if self.namespace.prometheus_access
            else self.namespace.namespace.cluster.prometheus_url
        )


class PrometheusClient(ApiBase):
    def get_current_slo_value(
        self,
        slo: SLODocumentSLOV1,
        slo_document_name: str,
        namespace_name: str,
        service_name: str,
        cluster_name: str,
    ) -> SLODetails | None:
        """
        Retrieve the current SLO value from Prometheus for provided SLO configuration.
        Returns an SLODetails instance if successful, or None on error.
        """
        template = jinja2.Template(slo.expr)
        prom_query = template.render({"window": slo.slo_parameters.window})
        try:
            current_slo_response = self._get(
                url=PROM_QUERY_URL, params={"query": (prom_query)}
            )
            current_slo_value = self._extract_current_slo_value(
                data=current_slo_response
            )
            return SLODetails(
                namespace_name=namespace_name,
                slo=slo,
                slo_document_name=slo_document_name,
                current_slo_value=current_slo_value,
                cluster_name=cluster_name,
                service_name=service_name,
            )
        except requests.exceptions.ConnectionError:
            logging.error(
                f"Connection error  getting current value for SLO: {slo.name} of document: {slo_document_name} for namespace: {namespace_name}"
            )
            raise
        except Exception as e:
            logging.error(
                f"Unexpected error getting current value for SLO: {slo.name} of document: {slo_document_name} for namespace: {namespace_name} details: {e}"
            )
            return None

    def _extract_current_slo_value(self, data: dict[str, Any]) -> float:
        result = data["data"]["result"]
        if not result:
            raise EmptySLOResult("prometheus returned empty result")
        slo_value = result[0]["value"]
        if not slo_value:
            raise EmptySLOValue("prometheus returned empty SLO value")
        slo_value = float(slo_value[1])
        if isnan(slo_value):
            raise InvalidSLOValue("slo value should be a number")
        return slo_value


class PrometheusClientMap:
    """
    A mapping from Prometheus URLs to PrometheusClient instances.
    """

    def __init__(
        self,
        secret_reader: SecretReaderBase,
        namespace_slo_documents: list[NamespaceSLODocument],
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
    ):
        self.secret_reader = secret_reader
        self.read_timeout = read_timeout
        self.max_retries = max_retries
        self.pc_map: dict[str, PrometheusClient] = self._build_pc_map(
            namespace_slo_documents
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()

    def get_prometheus_client(self, prom_url: str) -> PrometheusClient:
        return self.pc_map[prom_url]

    def _build_pc_map(
        self, namespace_slo_documents: list[NamespaceSLODocument]
    ) -> dict[str, PrometheusClient]:
        pc_map: dict[str, PrometheusClient] = {}
        for doc in namespace_slo_documents:
            key = doc.get_host_url()
            if key not in pc_map:
                prom_client = self.build_prom_client_from_namespace(doc.namespace)
                pc_map[key] = prom_client
        return pc_map

    def cleanup(self) -> None:
        for prom_client in self.pc_map.values():
            prom_client.cleanup()

    def build_auth_for_prometheus_access(
        self, prometheus_access: SLOExternalPrometheusAccessV1
    ) -> requests.auth.HTTPBasicAuth | None:
        """
        Build  authentication for  Prometheus endpoint referred in prometheusAccess section.
        """
        if prometheus_access.username and prometheus_access.password:
            username = self.secret_reader.read_secret(prometheus_access.username)
            password = self.secret_reader.read_secret(prometheus_access.password)
            return requests.auth.HTTPBasicAuth(username, password)
        return None

    def build_prom_client_from_namespace(
        self, namespace: SLONamespacesV1
    ) -> PrometheusClient:
        auth: requests.auth.HTTPBasicAuth | BearerTokenAuth | None
        if namespace.prometheus_access:
            prom_url = namespace.prometheus_access.url
            auth = self.build_auth_for_prometheus_access(namespace.prometheus_access)
            return PrometheusClient(
                host=prom_url,
                read_timeout=self.read_timeout,
                max_retries=self.max_retries,
                auth=auth,
            )
        if not namespace.namespace.cluster.automation_token:
            raise Exception(
                f"cluster {namespace.namespace.cluster.name} does not have automation token set"
            )
        auth = BearerTokenAuth(
            self.secret_reader.read_secret(namespace.namespace.cluster.automation_token)
        )
        return PrometheusClient(
            host=namespace.namespace.cluster.prometheus_url,
            read_timeout=self.read_timeout,
            max_retries=self.max_retries,
            auth=auth,
        )


class SLODocumentManager:
    """
    Manages  SLO document including authentication, querying, and SLO value extraction.
    """

    def __init__(
        self,
        slo_documents: list[SLODocument],
        secret_reader: SecretReaderBase,
        thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
    ):
        self.namespace_slo_documents = self._build_namespace_slo_documents(
            slo_documents
        )
        self.thread_pool_size = thread_pool_size
        self.secret_reader = secret_reader
        self.max_retries = max_retries
        self.read_timeout = read_timeout

    @staticmethod
    def _build_namespace_slo_documents(
        slo_documents: list[SLODocument],
    ) -> list[NamespaceSLODocument]:
        return [
            NamespaceSLODocument(
                name=slo_document.name,
                namespace=namespace,
                slos=slo_document.slos,
            )
            for slo_document in slo_documents
            for namespace in slo_document.namespaces
        ]

    def get_current_slo_list(self) -> list[SLODetails | None]:
        with PrometheusClientMap(
            secret_reader=self.secret_reader,
            namespace_slo_documents=self.namespace_slo_documents,
            read_timeout=self.read_timeout,
            max_retries=self.max_retries,
        ) as pc_map:
            current_slo_list_iterable = threaded.run(
                func=self._get_current_slo_details_list,
                pc_map=pc_map,
                iterable=self.namespace_slo_documents,
                thread_pool_size=self.thread_pool_size,
            )
            return list(itertools.chain.from_iterable(current_slo_list_iterable))

    def get_breached_slos(self) -> list[SLODetails]:
        current_slo_details_list = self.get_current_slo_list()
        missing_slos = [slo for slo in current_slo_details_list if not slo]
        if missing_slos:
            raise RuntimeError("slo validation failed due to retrival errors")
        return [
            slo
            for slo in current_slo_details_list
            if slo and slo.current_slo_value < slo.slo.slo_target
        ]

    @staticmethod
    def _get_current_slo_details_list(
        slo_document: NamespaceSLODocument,
        pc_map: PrometheusClientMap,
    ) -> list[SLODetails | None]:
        key = slo_document.get_host_url()
        prom_client = pc_map.get_prometheus_client(key)
        slo_details_list: list[SLODetails | None] = [
            prom_client.get_current_slo_value(
                slo=slo,
                slo_document_name=slo_document.name,
                namespace_name=slo_document.namespace.namespace.name,
                service_name=slo_document.namespace.namespace.app.name,
                cluster_name=slo_document.namespace.namespace.cluster.name,
            )
            for slo in slo_document.slos or []
        ]
        return slo_details_list
