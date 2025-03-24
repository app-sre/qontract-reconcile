import logging
from base64 import b64encode

from reconcile.gql_definitions.fragments.saas_slo_document import (
    SaasSLODocument,
    SLONamespacesV1,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.slo_details import PromCredentials, SLODetails


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
                prom_credentials=self._get_credentials_from_slo_namespace(namespace),
                slo=slo,
            )
            for slo_document in slo_documents
            for namespace in slo_document.namespaces
            if not namespace.slo_namespace or namespace.prometheus_access
            for slo in slo_document.slos or []
        ]
        return slo_details_list

    def _get_credentials_from_slo_namespace(
        self, namespace: SLONamespacesV1
    ) -> PromCredentials:
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
        return PromCredentials(
            prom_url=prom_url, prom_token=prom_token, is_basic_auth=is_basic_auth
        )

    def is_slo_breached(self) -> bool:
        breached_slo_list: list[SLODetails] = []
        for slo in self.slo_details_list:
            slo_value = slo.get_SLO_value()
            if slo_value < slo.slo.slo_target:
                logging.info(
                    f"SLO {slo.slo.name} from document {slo.slo_document_name} is breached. Expected value:{slo.slo.slo_target} current value:{slo_value}"
                )
                breached_slo_list.append(slo)
        return bool(breached_slo_list)
