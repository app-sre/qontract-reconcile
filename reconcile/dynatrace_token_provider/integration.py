import base64
import logging
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.metrics import (
    DTPClustersManagedGauge,
    DTPOrganizationErrorRate,
)
from reconcile.dynatrace_token_provider.ocm import Cluster, OCMClient
from reconcile.utils import (
    metrics,
)
from reconcile.utils.dynatrace.client import DynatraceAPITokenCreated, DynatraceClient
from reconcile.utils.ocm.base import (
    OCMClusterServiceLogCreateModel,
    OCMServiceLogSeverity,
)
from reconcile.utils.ocm.labels import subscription_label_filter
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "dynatrace-token-provider"
SYNCSET_ID = "ext-dynatrace-tokens-dtp"
SECRET_NAME = "dynatrace-token-dtp"
SECRET_NAMESPACE = "dynatrace"
DYNATRACE_INGESTION_TOKEN_NAME = "dynatrace-ingestion-token"
DYNATRACE_OPERATOR_TOKEN_NAME = "dynatrace-operator-token"


class DynatraceTokenProviderIntegrationParams(PydanticRunParams):
    ocm_organization_ids: set[str] | None = None


class ReconcileErrorSummary(Exception):
    def __init__(self, exceptions: Iterable[str]) -> None:
        self.exceptions = exceptions

    def __str__(self) -> str:
        formatted_exceptions = "\n".join([f"- {e}" for e in self.exceptions])
        return f"Reconcile exceptions:\n{formatted_exceptions}"


class DynatraceTokenProviderIntegration(
    QontractReconcileIntegration[DynatraceTokenProviderIntegrationParams]
):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        dependencies = Dependencies(
            secret_reader=self.secret_reader,
            dynatrace_client_by_tenant_id={},
            ocm_client_by_env_name={},
        )
        dependencies.populate()
        self.reconcile(dry_run=dry_run, dependencies=dependencies)

    def reconcile(self, dry_run: bool, dependencies: Dependencies) -> None:
        with metrics.transactional_metrics(self.name):
            unhandled_exceptions = []
            for ocm_env_name, ocm_client in dependencies.ocm_client_by_env_name.items():
                clusters: list[Cluster] = []
                try:
                    clusters = ocm_client.discover_clusters_by_labels(
                        label_filter=subscription_label_filter().like(
                            "key", dtp_label_key("%")
                        ),
                    )
                except Exception as e:
                    unhandled_exceptions.append(f"{ocm_env_name}: {e}")
                metrics.set_gauge(
                    DTPClustersManagedGauge(
                        integration=self.name,
                        ocm_env=ocm_env_name,
                    ),
                    len(clusters),
                )
                if not clusters:
                    continue
                if self.params.ocm_organization_ids:
                    clusters = [
                        cluster
                        for cluster in clusters
                        if cluster.organization_id in self.params.ocm_organization_ids
                    ]
                dtp_tenant_label_key = f"{dtp_label_key(None)}.tenant"
                existing_dtp_tokens = {}

                for cluster in clusters:
                    try:
                        with DTPOrganizationErrorRate(
                            integration=self.name,
                            ocm_env=ocm_env_name,
                            org_id=cluster.organization_id,
                        ):
                            tenant_id = cluster.dt_tenant
                            if not tenant_id:
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster_uuid=cluster.external_id,
                                    error=f"Missing label {dtp_tenant_label_key}",
                                )
                                continue
                            if (
                                tenant_id
                                not in dependencies.dynatrace_client_by_tenant_id
                            ):
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster_uuid=cluster.external_id,
                                    error=f"Dynatrace tenant {tenant_id} does not exist",
                                )
                                continue
                            dt_client = dependencies.dynatrace_client_by_tenant_id[
                                tenant_id
                            ]

                            if tenant_id not in existing_dtp_tokens:
                                existing_dtp_tokens[tenant_id] = (
                                    dt_client.get_token_ids_for_name_prefix(
                                        prefix="dtp-"
                                    )
                                )

                            self.process_cluster(
                                dry_run,
                                cluster,
                                dt_client,
                                ocm_client,
                                existing_dtp_tokens[tenant_id],
                                tenant_id,
                            )
                    except Exception as e:
                        unhandled_exceptions.append(
                            f"{ocm_env_name}/{cluster.organization_id}/{cluster.external_id}: {e}"
                        )

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)

    def process_cluster(
        self,
        dry_run: bool,
        cluster: Cluster,
        dt_client: DynatraceClient,
        ocm_client: OCMClient,
        existing_dtp_tokens: Iterable[str],
        tenant_id: str,
    ) -> None:
        existing_syncset = self.get_syncset(ocm_client, cluster)
        dt_api_url = f"https://{tenant_id}.live.dynatrace.com/api"
        if not existing_syncset:
            if not dry_run:
                try:
                    (ingestion_token, operator_token) = self.create_dynatrace_tokens(
                        dt_client, cluster.external_id
                    )
                    ocm_client.create_syncset(
                        cluster.id,
                        self.construct_syncset(
                            ingestion_token, operator_token, dt_api_url
                        ),
                    )
                except Exception as e:
                    _expose_errors_as_service_log(
                        ocm_client,
                        cluster.external_id,
                        f"DTP can't create Syncset with the tokens {str(e.args)}",
                    )
            logging.info(
                f"Ingestion and operator tokens created in Dynatrace for cluster {cluster.external_id}."
            )
            logging.info(
                f"SyncSet {SYNCSET_ID} created in cluster {cluster.external_id}."
            )
        else:
            tokens = self.get_tokens_from_syncset(existing_syncset)
            need_patching = False
            for token_name, token in tokens.items():
                if token.id not in existing_dtp_tokens:
                    need_patching = True
                    logging.info(f"{token_name} missing in Dynatrace.")
                    if token_name == DYNATRACE_INGESTION_TOKEN_NAME:
                        if not dry_run:
                            ingestion_token = self.create_dynatrace_ingestion_token(
                                dt_client, cluster.external_id
                            )
                            token.id = ingestion_token.id
                            token.token = ingestion_token.token
                        logging.info(
                            f"Ingestion token created in Dynatrace for cluster {cluster.external_id}."
                        )
                    elif token_name == DYNATRACE_OPERATOR_TOKEN_NAME:
                        if not dry_run:
                            operator_token = self.create_dynatrace_operator_token(
                                dt_client, cluster.external_id
                            )
                            token.id = operator_token.id
                            token.token = operator_token.token
                        logging.info(
                            f"Operator token created in Dynatrace for cluster {cluster.external_id}."
                        )
                elif token_name == DYNATRACE_INGESTION_TOKEN_NAME:
                    ingestion_token = token
                elif token_name == DYNATRACE_OPERATOR_TOKEN_NAME:
                    operator_token = token
            if need_patching:
                if not dry_run:
                    patch_syncset_payload = self.construct_base_syncset(
                        ingestion_token=ingestion_token,
                        operator_token=operator_token,
                        dt_api_url=dt_api_url,
                    )
                    try:
                        logging.info(f"Patching syncset {SYNCSET_ID}.")
                        ocm_client.patch_syncset(
                            cluster_id=cluster.id,
                            syncset_id=SYNCSET_ID,
                            syncset_map=patch_syncset_payload,
                        )
                    except Exception as e:
                        _expose_errors_as_service_log(
                            ocm_client,
                            cluster.external_id,
                            f"DTP can't patch Syncset {SYNCSET_ID} due to {str(e.args)}",
                        )
                logging.info(f"Syncset {SYNCSET_ID} patched.")

    def get_syncset(self, ocm_client: OCMClient, cluster: Cluster) -> dict[str, Any]:
        try:
            syncset = ocm_client.get_syncset(cluster.id, SYNCSET_ID)
        except Exception as e:
            if "Not Found" in e.args[0]:
                syncset = None
            else:
                raise e
        return syncset

    def get_tokens_from_syncset(
        self, syncset: Mapping[str, Any]
    ) -> dict[str, DynatraceAPITokenCreated]:
        tokens: dict[str, Any] = {}
        for resource in syncset["resources"]:
            if resource["kind"] == "Secret":
                operator_token_id = self.base64_decode(resource["data"]["apiTokenId"])
                operator_token = self.base64_decode(resource["data"]["apiToken"])
                ingest_token_id = self.base64_decode(
                    resource["data"]["dataIngestTokenId"]
                )
                ingest_token = self.base64_decode(resource["data"]["dataIngestToken"])
        tokens[DYNATRACE_INGESTION_TOKEN_NAME] = DynatraceAPITokenCreated(
            id=ingest_token_id,
            token=ingest_token,
        )
        tokens[DYNATRACE_OPERATOR_TOKEN_NAME] = DynatraceAPITokenCreated(
            id=operator_token_id,
            token=operator_token,
        )
        return tokens

    def construct_base_syncset(
        self,
        ingestion_token: DynatraceAPITokenCreated,
        operator_token: DynatraceAPITokenCreated,
        dt_api_url: str,
    ) -> dict[str, Any]:
        return {
            "kind": "SyncSet",
            "resources": [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": SECRET_NAME, "namespace": SECRET_NAMESPACE},
                    "data": {
                        "apiUrl": f"{self.base64_encode_str(dt_api_url)}",
                        "dataIngestTokenId": f"{self.base64_encode_str(ingestion_token.id)}",
                        "dataIngestToken": f"{self.base64_encode_str(ingestion_token.token)}",
                        "apiTokenId": f"{self.base64_encode_str(operator_token.id)}",
                        "apiToken": f"{self.base64_encode_str(operator_token.token)}",
                    },
                },
            ],
        }

    def base64_decode(self, encoded: str) -> str:
        data_bytes = base64.b64decode(encoded)
        return data_bytes.decode("utf-8")

    def base64_encode_str(self, string: str) -> str:
        data_bytes = string.encode("utf-8")
        encoded = base64.b64encode(data_bytes)
        return encoded.decode("utf-8")

    def construct_syncset(
        self,
        ingestion_token: DynatraceAPITokenCreated,
        operator_token: DynatraceAPITokenCreated,
        dt_api_url: str,
    ) -> dict[str, Any]:
        syncset = self.construct_base_syncset(
            ingestion_token=ingestion_token,
            operator_token=operator_token,
            dt_api_url=dt_api_url,
        )
        syncset["id"] = SYNCSET_ID
        return syncset

    def create_dynatrace_ingestion_token(
        self, dt_client: DynatraceClient, cluster_uuid: str
    ) -> DynatraceAPITokenCreated:
        return dt_client.create_api_token(
            name=f"dtp-ingestion-token-{cluster_uuid}",
            scopes=["metrics.ingest", "logs.ingest", "events.ingest"],
        )

    def create_dynatrace_operator_token(
        self, dt_client: DynatraceClient, cluster_uuid: str
    ) -> DynatraceAPITokenCreated:
        return dt_client.create_api_token(
            name=f"dtp-operator-token-{cluster_uuid}",
            scopes=[
                "activeGateTokenManagement.create",
                "entities.read",
                "settings.write",
                "settings.read",
                "DataExport",
                "InstallerDownload",
            ],
        )

    def create_dynatrace_tokens(
        self, dt_client: DynatraceClient, cluster_uuid: str
    ) -> tuple[DynatraceAPITokenCreated, DynatraceAPITokenCreated]:
        ingestion_token = self.create_dynatrace_ingestion_token(dt_client, cluster_uuid)
        operation_token = self.create_dynatrace_operator_token(dt_client, cluster_uuid)
        return (ingestion_token, operation_token)


def dtp_label_key(config_atom: str | None) -> str:
    return sre_capability_label_key("dtp", config_atom)


def _expose_errors_as_service_log(
    ocm_api: OCMClient, cluster_uuid: str, error: str
) -> None:
    ocm_api.create_service_log(
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid=cluster_uuid,
            severity=OCMServiceLogSeverity.Warning,
            summary="Dynatrace Token Provider Errors",
            description=f"\n {error}",
            service_name=QONTRACT_INTEGRATION,
        ),
        dedup_interval=timedelta(days=1),
    )
