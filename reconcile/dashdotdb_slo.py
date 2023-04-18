from collections.abc import Iterable
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
)

import jinja2
import requests
from requests import Response
from sretoolbox.utils import threaded

from reconcile.dashdotdb_base import (
    LOG,
    DashdotdbBase,
)
from reconcile.gql_definitions.dashdotdb_slo.slo_documents_query import (
    SLODocumentV1,
    query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)

QONTRACT_INTEGRATION = "dashdotdb-slo"


def get_slo_documents() -> list[SLODocumentV1]:
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

    def _post(self, service_slos: Iterable[ServiceSLO]) -> Optional[Response]:
        for item in service_slos:
            LOG.debug(f"About to POST SLO JSON item to dashdotDB:\n{item}\n")

        response = None

        for item in service_slos:
            slo_name = item.name
            endpoint = f"{self.dashdotdb_url}/api/v1/" f"serviceslometrics/{slo_name}"
            payload = item.dashdot_payload()
            if self.dry_run:
                continue

            LOG.info("%s syncing slo %s", self.logmarker, slo_name)
            response = self._do_post(endpoint, payload)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as details:
                LOG.error("%s error posting %s - %s", self.logmarker, slo_name, details)

            LOG.info("%s slo %s synced", self.logmarker, slo_name)
        return response

    def _get_service_slo(self, slo_document: SLODocumentV1) -> list[ServiceSLO]:
        LOG.debug("SLO: processing %s", slo_document.name)
        result: list[ServiceSLO] = []
        for ns in slo_document.namespaces:
            promurl = ns.cluster.prometheus_url
            if not ns.cluster.automation_token:
                LOG.error(
                    "namespace does not have automation token set %s - skipping", ns
                )
                continue
            promtoken = self._get_automation_token(ns.cluster.automation_token)
            for slo in slo_document.slos or []:
                unit = slo.slo_target_unit
                expr = slo.expr
                template = jinja2.Template(expr)
                window = slo.slo_parameters.window
                promquery = template.render({"window": window})
                prom_response = self._promget(
                    url=promurl,
                    params={"query": (f"{promquery}")},
                    token=promtoken,
                )
                prom_result = prom_response["data"]["result"]
                if not prom_result:
                    continue

                slo_value = prom_result[0]["value"]
                if not slo_value:
                    continue

                slo_value = float(slo_value[1])
                slo_target = float(slo.slo_target)

                # In Dash.DB we want to always store SLOs in percentages
                if unit == "percent_0_1":
                    slo_value *= 100
                    slo_target *= 100

                result.append(
                    ServiceSLO(
                        name=slo.name,
                        sli_type=slo.sli_type,
                        namespace_name=ns.name,
                        cluster_name=ns.cluster.name,
                        service_name=ns.app.name,
                        value=slo_value,
                        target=slo_target,
                        slo_doc_name=slo_document.name,
                    )
                )
        return result

    def run(self) -> None:
        slo_documents = get_slo_documents()

        service_slos: list[list[ServiceSLO]] = threaded.run(
            func=self._get_service_slo,
            iterable=slo_documents,
            thread_pool_size=self.thread_pool_size,
        )

        self._get_token()
        threaded.run(
            func=self._post,
            iterable=service_slos,
            thread_pool_size=self.thread_pool_size,
        )
        self._close_token()


def run(dry_run: bool = False, thread_pool_size: int = 10) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    dashdotdb_slo = DashdotdbSLO(
        dry_run=dry_run, thread_pool_size=thread_pool_size, secret_reader=secret_reader
    )
    dashdotdb_slo.run()
