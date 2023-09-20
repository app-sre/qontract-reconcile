import logging
import sys
from datetime import timedelta
from typing import (
    Any,
    Mapping,
    Optional,
    Union,
)

from dynatrace import Dynatrace
from dynatrace.environment_v2.tokens_api import ApiTokenCreated
from pydantic import BaseModel

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.dynatrace_token_provider import (
    dynatrace_bootstrap_tokens,
)
from reconcile.gql_definitions.dynatrace_token_provider.dynatrace_bootstrap_tokens import (
    DynatraceEnvironmentQueryData,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.metrics import (
    CounterMetric,
    ErrorRateMetricSet,
)
from reconcile.utils.ocm.base import (
    OCMClusterServiceLogCreateModel,
    OCMServiceLogSeverity,
)
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import subscription_label_filter
from reconcile.utils.ocm.service_log import create_service_log
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.ocm.syncsets import (
    create_syncset,
    get_syncset,
    patch_syncset,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import SecretReaderBase

QONTRACT_INTEGRATION = "dynatrace-token-provider"
SYNCSET_ID = "ext-dynatrace-tokens"
SECRET_NAME = "dynatrace-token-dtp"
DYNATRACE_INGESTION_TOKEN_NAME = "dynatrace-ingestion-token"
DYNATRACE_OPERATOR_TOKEN_NAME = "dynatrace-operator-token"


class DynatraceTokenProviderIntegrationParams(PydanticRunParams):
    ocm_organization_ids: Optional[set[str]] = None


class ReconcileErrorSummary(Exception):
    def __init__(self, exceptions: list[str]) -> None:
        self.exceptions = exceptions

    def __str__(self) -> str:
        formatted_exceptions = "\n".join([f"- {e}" for e in self.exceptions])
        return f"Reconcile exceptions:\n{ formatted_exceptions }"


class DTPBaseMetric(BaseModel):
    integration: str
    ocm_env: str


class DTPOrganizationReconcileCounter(DTPBaseMetric, CounterMetric):
    org_id: str

    @classmethod
    def name(cls) -> str:
        return "dtp_organization_reconciled"


class DTPOrganizationReconcileErrorCounter(DTPBaseMetric, CounterMetric):
    org_id: str

    @classmethod
    def name(cls) -> str:
        return "dtp_organization_reconcile_errors"


class DTPOrganizationErrorRate(ErrorRateMetricSet):
    def __init__(self, integration: str, org_id: str, ocm_env: str) -> None:
        super().__init__(
            counter=DTPOrganizationReconcileCounter(
                integration=integration,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
            error_counter=DTPOrganizationReconcileErrorCounter(
                integration=integration,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
        )


class DynatraceTokenProviderIntegration(
    QontractReconcileIntegration[DynatraceTokenProviderIntegrationParams]
):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        with metrics.transactional_metrics(self.name):
            unhandled_exceptions = []
            for env in self.get_ocm_environments():
                ocm_client = init_ocm_base_client(env, self.secret_reader)
                clusters = discover_clusters_by_labels(
                    ocm_api=ocm_client,
                    label_filter=subscription_label_filter().like(
                        "key", dtp_label_key("%")
                    ),
                )
                if not clusters:
                    continue
                if self.params.ocm_organization_ids:
                    clusters = [
                        cluster
                        for cluster in clusters
                        if cluster.organization_id in self.params.ocm_organization_ids
                    ]
                dt_clients = self.get_all_dynatrace_clients(self.secret_reader)
                dtp_tenant_label_key = f"{dtp_label_key(None)}.tenant"
                existing_dtp_tokens = {}

                for cluster in clusters:
                    try:
                        with DTPOrganizationErrorRate(
                            integration=self.name,
                            ocm_env=env.name,
                            org_id=cluster.organization_id,
                        ):
                            tenant_id = cluster.labels.get_label_value(
                                dtp_tenant_label_key
                            )
                            if not tenant_id:
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster_uuid=cluster.ocm_cluster.external_id,
                                    error=f"Missing label {dtp_tenant_label_key}",
                                )
                                continue
                            if tenant_id not in dt_clients:
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster_uuid=cluster.ocm_cluster.external_id,
                                    error=f"Dynatrace tenant {tenant_id} does not exist",
                                )
                                continue

                            if tenant_id not in existing_dtp_tokens:
                                existing_dtp_tokens[
                                    tenant_id
                                ] = self.get_all_dtp_tokens(dt_clients[tenant_id])

                            self.process_cluster(
                                dry_run,
                                cluster,
                                dt_clients[tenant_id],
                                ocm_client,
                                existing_dtp_tokens[tenant_id],
                                tenant_id,
                            )
                    except Exception as e:
                        unhandled_exceptions.append(
                            f"{env}/{cluster.organization_id}/{cluster.ocm_cluster.external_id}: {e}"
                        )

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)
        sys.exit(0)

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(gql.get_api().query).environments

    def get_all_dynatrace_tenants(self) -> DynatraceEnvironmentQueryData:
        dt_tenants = dynatrace_bootstrap_tokens.query(query_func=gql.get_api().query)
        return dt_tenants

    def get_all_dynatrace_clients(
        self, secret_reader: SecretReaderBase
    ) -> Mapping[str, Dynatrace]:
        dt_tenants = self.get_all_dynatrace_tenants()
        dynatrace_clients = {}
        if not dt_tenants.environments:
            raise RuntimeError("No Dynatrace environment defined.")
        for tenant in dt_tenants.environments:
            dt_bootstrap_token = secret_reader.read_secret(tenant.bootstrap_token)
            dt_client = Dynatrace(
                tenant.environment_url,
                dt_bootstrap_token,
            )
            tenant_id = tenant.environment_url.split(".")[0].removeprefix("https://")
            dynatrace_clients[tenant_id] = dt_client
        return dynatrace_clients

    def get_all_dtp_tokens(self, dt_client: Dynatrace) -> list[str]:
        try:
            dt_tokens = dt_client.tokens.list()
        except Exception as e:
            logging.error("Failed to retrieve all dtp tokens")
            raise e
        return [token.id for token in dt_tokens if token.name.startswith("dtp-")]

    def process_cluster(
        self,
        dry_run: bool,
        cluster: ClusterDetails,
        dt_client: Dynatrace,
        ocm_client: OCMBaseClient,
        existing_dtp_tokens: list[str],
        tenant_id: str,
    ) -> None:
        existing_syncset = self.get_syncset(ocm_client, cluster)
        dt_env_url = f"https://{tenant_id}.live.dynatrace.com"
        if not existing_syncset:
            if not dry_run:
                try:
                    (ingestion_token, operator_token) = self.create_dynatrace_tokens(
                        dt_client, cluster.ocm_cluster.external_id
                    )
                    create_syncset(
                        ocm_client,
                        cluster.ocm_cluster.id,
                        self.construct_syncset(
                            ingestion_token, operator_token, dt_env_url
                        ),
                    )
                except Exception as e:
                    _expose_errors_as_service_log(
                        ocm_client,
                        cluster.ocm_cluster.external_id,
                        f"DTP can't create Syncset with the tokens {str(e.args)}",
                    )
            logging.info(
                f"Ingestion and operator tokens created in Dynatrace for cluster {cluster.ocm_cluster.external_id}."
            )
            logging.info(
                f"SyncSet {SYNCSET_ID} created in cluster {cluster.ocm_cluster.external_id}."
            )
        else:
            tokens = self.get_tokens_from_syncset(existing_syncset)
            need_patching = False
            for token_name, token in tokens.items():
                if token["id"] not in existing_dtp_tokens:
                    need_patching = True
                    logging.info(f"{token_name} missing in Dynatrace.")
                    if token_name == DYNATRACE_INGESTION_TOKEN_NAME:
                        if not dry_run:
                            ingestion_token = self.create_dynatrace_ingestion_token(
                                dt_client, cluster.ocm_cluster.external_id
                            )
                            token["id"] = ingestion_token.id
                            token["token"] = ingestion_token.token
                        logging.info(
                            f"Ingestion token created in Dynatrace for cluster {cluster.ocm_cluster.external_id}."
                        )
                    elif token_name == DYNATRACE_OPERATOR_TOKEN_NAME:
                        if not dry_run:
                            operator_token = self.create_dynatrace_operator_token(
                                dt_client, cluster.ocm_cluster.external_id
                            )
                            token["id"] = operator_token.id
                            token["token"] = operator_token.token
                        logging.info(
                            f"Operator token created in Dynatrace for cluster {cluster.ocm_cluster.external_id}."
                        )
                else:
                    if token_name == DYNATRACE_INGESTION_TOKEN_NAME:
                        ingestion_token = ApiTokenCreated(raw_element=token)
                    elif token_name == DYNATRACE_OPERATOR_TOKEN_NAME:
                        operator_token = ApiTokenCreated(raw_element=token)
            if need_patching:
                if not dry_run:
                    patch_syncset_payload = self.construct_base_syncset(
                        ingestion_token=ingestion_token,
                        operator_token=operator_token,
                        dt_api_url=dt_env_url,
                    )
                    try:
                        logging.info(f"Patching syncset {SYNCSET_ID}.")
                        patch_syncset(
                            ocm_client,
                            cluster_id=cluster.ocm_cluster.id,
                            syncset_id=SYNCSET_ID,
                            syncset_map=patch_syncset_payload,
                        )
                    except Exception as e:
                        _expose_errors_as_service_log(
                            ocm_client,
                            cluster.ocm_cluster.external_id,
                            f"DTP can't patch Syncset {SYNCSET_ID} due to {str(e.args)}",
                        )
                logging.info(f"Syncset {SYNCSET_ID} patched.")

    def get_syncset(
        self, ocm_client: OCMBaseClient, cluster: ClusterDetails
    ) -> Mapping:
        try:
            syncset = get_syncset(ocm_client, cluster.ocm_cluster.id, SYNCSET_ID)
        except Exception as e:
            if "Not Found" in e.args[0]:
                syncset = None
            else:
                raise e
        return syncset

    def get_tokens_from_syncset(self, syncset: Mapping) -> Mapping:
        tokens = {}
        for resource in syncset["resources"]:
            if resource["kind"] == "Secret":
                operator_token_id = resource["data"]["apiTokenId"]
                operator_token = resource["data"]["apiToken"]
                ingest_token_id = resource["data"]["dataIngestTokenId"]
                ingest_token = resource["data"]["dataIngestToken"]
        tokens[DYNATRACE_INGESTION_TOKEN_NAME] = {
            "id": ingest_token_id,
            "token": ingest_token,
        }
        tokens[DYNATRACE_OPERATOR_TOKEN_NAME] = {
            "id": operator_token_id,
            "token": operator_token,
        }
        return tokens

    def construct_base_syncset(
        self,
        ingestion_token: ApiTokenCreated,
        operator_token: ApiTokenCreated,
        dt_api_url: str,
    ) -> dict[str, Any]:
        return {
            "kind": "SyncSet",
            "resources": [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": SECRET_NAME},
                    "data": {
                        "apiUrl": f"{dt_api_url}",
                        "dataIngestTokenId": f"{ingestion_token.id}",
                        "dataIngestToken": f"{ingestion_token.token}",
                        "apiTokenId": f"{operator_token.id}",
                        "apiToken": f"{operator_token.token}",
                    },
                },
            ],
        }

    def construct_syncset(
        self,
        ingestion_token: ApiTokenCreated,
        operator_token: ApiTokenCreated,
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
        self, dt_client: Dynatrace, cluster_uuid: str
    ) -> ApiTokenCreated:
        return dt_client.tokens.create(
            name=f"dtp-ingestion-token-{cluster_uuid}",
            scopes=["metrics.ingest", "logs.ingest", "events.ingest"],
        )

    def create_dynatrace_operator_token(
        self, dt_client: Dynatrace, cluster_uuid: str
    ) -> ApiTokenCreated:
        return dt_client.tokens.create(
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
        self, dt_client: Dynatrace, cluster_uuid: str
    ) -> tuple[ApiTokenCreated, ApiTokenCreated]:
        ingestion_token = self.create_dynatrace_ingestion_token(dt_client, cluster_uuid)
        operation_token = self.create_dynatrace_operator_token(dt_client, cluster_uuid)
        return (ingestion_token, operation_token)


def dtp_label_key(config_atom: Union[str, None]) -> str:
    return sre_capability_label_key("dtp", config_atom)


def _expose_errors_as_service_log(
    ocm_api: OCMBaseClient, cluster_uuid: str, error: str
) -> None:
    create_service_log(
        ocm_api=ocm_api,
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid=cluster_uuid,
            severity=OCMServiceLogSeverity.Warning,
            summary="Cluster upgrade policy validation errors",
            description=f"\n {error}",
            service_name=QONTRACT_INTEGRATION,
        ),
        dedup_interval=timedelta(days=1),
    )
