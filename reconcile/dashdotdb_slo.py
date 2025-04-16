import itertools
from dataclasses import dataclass
from typing import Any

import requests
from requests.exceptions import ConnectionError
from sretoolbox.utils import threaded

from reconcile.dashdotdb_base import (
    LOG,
    DashdotdbBase,
)
from reconcile.gql_definitions.dashdotdb_slo.slo_documents_query import (
    query,
)
from reconcile.gql_definitions.fragments.saas_slo_document import SLODocument
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)
from reconcile.utils.slo_document_manager import (
    SLODetails,
    SLODocumentManager,
)

QONTRACT_INTEGRATION = "dashdotdb-slo"


def get_slo_documents() -> list[SLODocument]:
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    return list(data.slo_documents or [])


@dataclass
class ServiceSLO:
    name: str
    sli_type: str
    slo_doc_name: str
    namespace_name: str
    cluster_name: str
    service_name: str
    value: float
    target: float

    def dashdot_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "SLIType": self.sli_type,
            "SLODoc": {"name": self.slo_doc_name},
            "namespace": {"name": self.namespace_name},
            "cluster": {"name": self.cluster_name},
            "service": {"name": self.service_name},
            "value": self.value,
            "target": self.target,
        }


class DashdotdbSLO(DashdotdbBase):
    def __init__(
        self, dry_run: bool, thread_pool_size: int, secret_reader: SecretReaderBase
    ) -> None:
        super().__init__(
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            marker="DDDB_SLO:",
            scope="serviceslometrics",
            secret_reader=secret_reader,
        )

    @staticmethod
    def get_dash_dot_db_payload(slo: SLODetails) -> dict[str, Any]:
        return {
            "name": slo.slo.name,
            "SLIType": slo.slo.sli_type,
            "SLODoc": {"name": slo.slo_document_name},
            "namespace": {"name": slo.namespace_name},
            "cluster": {"name": slo.cluster_name},
            "service": {"name": slo.service_name},
            "value": slo.current_slo_value,
            "target": slo.slo.slo_target,
        }

    def _post(self, service_slo: SLODetails) -> None:
        LOG.debug(f"About to POST SLO JSON item to dashdotDB:\n{service_slo}\n")
        slo_name = service_slo.slo.name
        endpoint = f"{self.dashdotdb_url}/api/v1/serviceslometrics/{slo_name}"
        if service_slo.slo.slo_target_unit == "percent_0_1":
            service_slo.current_slo_value *= 100
            service_slo.slo.slo_target *= 100
        payload = self.get_dash_dot_db_payload(service_slo)
        if not self.dry_run:
            LOG.info("%s syncing slo %s", self.logmarker, slo_name)
            try:
                response = self._do_post(endpoint, payload)
                response.raise_for_status()
            except (
                requests.exceptions.HTTPError,
                requests.exceptions.InvalidJSONError,
            ) as details:
                LOG.error("%s error posting %s - %s", self.logmarker, slo_name, details)

            LOG.info("%s slo %s synced", self.logmarker, slo_name)

    @staticmethod
    def get_current_slo_details(slo_manager: SLODocumentManager) -> list[SLODetails]:
        return slo_manager.get_slo_details_list()

    @staticmethod
    def check_and_raise_exception(exceptions: list[Exception]) -> None:
        connection_exceptions = [
            connection_exception
            for connection_exception in exceptions
            if isinstance(connection_exception, ConnectionError)
        ]
        if connection_exceptions:
            raise RuntimeError(
                f"Found exceptions while getting the slo details {connection_exceptions}"
            )
        for slo_exception in exceptions:
            LOG.error(slo_exception)

    def run(self) -> None:
        slo_documents = get_slo_documents()

        slo_document_manager_list = SLODocumentManager.get_slo_document_manager_list(
            slo_documents=slo_documents,
            secret_reader=self.secret_reader,
            thread_pool_size=self.thread_pool_size,
        )

        slo_details_list = threaded.run(
            func=self.get_current_slo_details,
            iterable=slo_document_manager_list,
            thread_pool_size=self.thread_pool_size,
        )

        slo_details_list = list(itertools.chain.from_iterable(slo_details_list))
        slo_exceptions = [slo for slo in slo_details_list if isinstance(slo, Exception)]
        valid_slo_list = [slo for slo in slo_details_list if slo not in slo_exceptions]

        self._get_token()
        threaded.run(
            func=self._post,
            iterable=valid_slo_list,
            thread_pool_size=self.thread_pool_size,
        )
        self._close_token()
        if slo_exceptions:
            self.check_and_raise_exception(slo_exceptions)


def run(dry_run: bool = False, thread_pool_size: int = 10) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    dashdotdb_slo = DashdotdbSLO(
        dry_run=dry_run, thread_pool_size=thread_pool_size, secret_reader=secret_reader
    )
    dashdotdb_slo.run()


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {doc.name: doc.dict() for doc in get_slo_documents()}
