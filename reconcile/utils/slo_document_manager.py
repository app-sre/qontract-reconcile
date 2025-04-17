from dataclasses import dataclass
from math import isnan
from typing import Any

import jinja2
import requests
from sretoolbox.utils import threaded

from reconcile.gql_definitions.fragments.saas_slo_document import (
    SLODocument,
    SLODocumentSLOV1,
    SLONamespacesV1,
)
from reconcile.utils.rest_api_base import ApiBase
from reconcile.utils.secret_reader import SecretReaderBase

PROM_QUERY_URL = "api/v1/query"

DEFAULT_READ_TIMEOUT = 30
DEFAULT_RETRIES = 5


class EmptySLOResult(Exception):
    pass


class EmptySLOValue(Exception):
    pass


class InvalidSLOValue(Exception):
    pass


@dataclass
class PromCredentials:
    prom_url: str
    is_basic_auth: bool
    prom_token: str
    username: str
    password: str

    def build_session(self) -> requests.Session:
        session = requests.Session()
        if self.is_basic_auth:
            session.auth = requests.auth.HTTPBasicAuth(self.username, self.password)
        else:
            session.headers.update({"Authorization": f"Bearer {self.prom_token}"})
        return session


@dataclass
class SLODetails:
    namespace_name: str
    slo_document_name: str
    cluster_name: str
    slo: SLODocumentSLOV1
    service_name: str
    current_slo_value: float


class SLODocumentManager(ApiBase):
    """
    Manages  SLO document including authentication, querying, and SLO value extraction.
    """

    def __init__(
        self,
        namespace: SLONamespacesV1,
        slo_document_name: str,
        slos: list[SLODocumentSLOV1] | None,
        secret_reader: SecretReaderBase,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        thread_pool_size: int = 1,
    ):
        self.slos = slos
        self.namespace = namespace
        self.thread_pool_size = thread_pool_size
        self.slo_document_name = slo_document_name
        self.secret_reader = secret_reader
        self.prom_credentials = self._get_credentials_from_slo_namespace(namespace)
        super().__init__(
            host=self.prom_credentials.prom_url,
            session=self.prom_credentials.build_session(),
            read_timeout=read_timeout,
            max_retries=max_retries,
        )

    @classmethod
    def get_slo_document_manager_list(
        cls,
        slo_documents: list[SLODocument],
        secret_reader: SecretReaderBase,
        thread_pool_size: int = 1,
        read_timeout: int = DEFAULT_READ_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
    ) -> list["SLODocumentManager"]:
        """
        Creates a list of SLODocumentManager instances from a list of SLO documents.
        """
        slo_details_manager_list = [
            SLODocumentManager(
                namespace=namespace,
                slo_document_name=slo_document.name,
                slos=slo_document.slos,
                secret_reader=secret_reader,
                thread_pool_size=thread_pool_size,
                read_timeout=read_timeout,
                max_retries=max_retries,
            )
            for slo_document in slo_documents
            for namespace in slo_document.namespaces
        ]
        return slo_details_manager_list

    def _get_credentials_from_slo_namespace(
        self, namespace: SLONamespacesV1
    ) -> PromCredentials:
        """
        Extracts prometheus URL and credentials required to query prometheus endpoint.
        """
        prom_url: str = ""
        prom_token: str = ""
        username: str = ""
        password: str = ""
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
        return PromCredentials(
            prom_url=prom_url,
            prom_token=prom_token,
            is_basic_auth=is_basic_auth,
            username=username,
            password=password,
        )

    def _extract_current_slo_value(self, data: Any, slo_name: str) -> float:
        result = data["data"]["result"]
        if not result:
            raise EmptySLOResult(
                f"prometheus returned empty result for SLO: {slo_name} of SLO document: {self.slo_document_name}"
            )
        slo_value = result[0]["value"]
        if not slo_value:
            raise EmptySLOValue(
                f"prometheus returned empty SLO value for SLO: {slo_name} of SLO document: {self.slo_document_name}"
            )
        slo_value = float(slo_value[1])
        if isnan(slo_value):
            raise InvalidSLOValue(
                f"invalid format for SLO: {slo_name} of SLO document: {self.slo_document_name}"
            )
        return slo_value

    def _get_slo_details(self, slo: SLODocumentSLOV1) -> SLODetails:
        """
        Build SLODetail object by retriving the current_value of the SLO from prometheus.
        """
        template = jinja2.Template(slo.expr)
        prom_query = template.render({"window": slo.slo_parameters.window})
        current_slo_response = self._get(
            url=PROM_QUERY_URL, params={"query": (f"{prom_query}")}
        )
        slo_details = SLODetails(
            namespace_name=self.namespace.namespace.name,
            slo_document_name=self.slo_document_name,
            cluster_name=self.namespace.namespace.cluster.name,
            service_name=self.namespace.namespace.app.name,
            slo=slo,
            current_slo_value=self._extract_current_slo_value(
                current_slo_response, slo.name
            ),
        )
        return slo_details

    def get_slo_details_list(self) -> list[SLODetails]:
        slo_details_list = threaded.run(
            self._get_slo_details,
            self.slos,
            self.thread_pool_size,
            return_exceptions=True,
        )
        return slo_details_list
