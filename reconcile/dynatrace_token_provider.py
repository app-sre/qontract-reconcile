import logging
import sys
from datetime import timedelta
from typing import Optional

from dynatrace import Dynatrace
from dynatrace.environment_v2.tokens_api import ApiTokenCreated
from pydantic import BaseModel

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
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
from reconcile.utils.ocm.clusters import discover_clusters_by_labels
from reconcile.utils.ocm.labels import subscription_label_filter
from reconcile.utils.ocm.service_log import create_service_log
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "dynatrace-token-provider"
SyncSet_ID = "ext-dynatrace-tokens"


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

                for cluster in clusters:
                    with DTPOrganizationErrorRate(
                        integration=self.name,
                        ocm_env=env.name,
                        org_id=cluster.organization_id,
                    ):
                        if self.params.ocm_organization_ids:
                            if (
                                cluster.organization_id
                                not in self.params.ocm_organization_ids
                            ):
                                continue

                        if cluster.labels:
                            dt_tenant_id = cluster.labels.get_label_value(
                                f"{dtp_label_key('')}.tenant"
                            )
                            dt_bootstrap_token = self.secret_reader.read(
                                {
                                    "path": f"app-sre/creds/dynatrace/redhat-aws/bootstrap-api-tokens/{dt_tenant_id}",
                                    "field": "token",
                                }
                            )

                            dt_client = Dynatrace(
                                f"https://{dt_tenant_id}.live.dynatrace.com/",
                                dt_bootstrap_token,
                            )

                            if cluster.ocm_cluster.external_configuration:
                                syncset_path = (
                                    cluster.ocm_cluster.external_configuration.syncsets[
                                        "href"
                                    ]
                                )
                            else:
                                unhandled_exceptions.append(
                                    f"{env}/{cluster.organization_id}: Failed to get cluster's external_configuration"
                                )

                            try:
                                existing_syncsets = ocm_client.get(syncset_path)
                            except Exception as e:
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster.ocm_cluster.external_id,
                                    str(e.args),
                                )
                                unhandled_exceptions.append(
                                    f"{env}/{cluster.organization_id}: {e}"
                                )

                            ingestion_token = None
                            operator_token = None

                            if existing_syncsets["size"] == 0 or not [
                                dt_token_syncset
                                for dt_token_syncset in existing_syncsets["items"]
                                if dt_token_syncset["id"] == "ext-dynatrace-tokens"
                            ]:
                                if not dry_run:
                                    (
                                        ingestion_token,
                                        operator_token,
                                    ) = self.create_dynatrace_tokens(
                                        dt_client, cluster.ocm_cluster.external_id
                                    )
                                    logging.info(
                                        f"Tokens: {ingestion_token.id},{operator_token.id} created in Dynatrace environment: {dt_tenant_id}"
                                    )
                                else:
                                    logging.info(
                                        f"Would have created ingestion and operation token in Dynatrace environment: {dt_tenant_id}"
                                    )

                            if existing_syncsets["size"] > 0:
                                for existing_syncset in existing_syncsets["items"]:
                                    if existing_syncset["id"] == SyncSet_ID:
                                        for resource in existing_syncset["resources"]:
                                            if resource["kind"] == "Secret":
                                                token_id = resource["data"]["id"]
                                                try:
                                                    dt_client.tokens.get(token_id)
                                                except Exception as e:
                                                    if "does not exist" in e.args[0]:
                                                        if (
                                                            "ingestion"
                                                            in resource["metadata"][
                                                                "name"
                                                            ]
                                                        ):
                                                            if not dry_run:
                                                                ingestion_token = self.create_dynatrace_ingestion_token(
                                                                    dt_client,
                                                                    cluster.ocm_cluster.external_id,
                                                                )
                                                                logging.info(
                                                                    f"Token: {ingestion_token.id} created in Dynatrace environment: {dt_tenant_id}"
                                                                )
                                                            else:
                                                                logging.info(
                                                                    "Would create ingestion token in Dynatrace"
                                                                )
                                                        elif (
                                                            "operator"
                                                            in resource["metadata"][
                                                                "name"
                                                            ]
                                                        ):
                                                            if not dry_run:
                                                                operator_token = self.create_dynatrace_operator_token(
                                                                    dt_client,
                                                                    cluster.ocm_cluster.external_id,
                                                                )
                                                                logging.info(
                                                                    f"Token: {operator_token.id} created in Dynatrace environment: {dt_tenant_id}"
                                                                )
                                                            else:
                                                                logging.info(
                                                                    "Would create operator token in Dynatrace"
                                                                )
                                                    unhandled_exceptions.append(
                                                        f"{env}/{cluster.organization_id}: {e}"
                                                    )
                                        break

                            if ingestion_token and operator_token:
                                if not dry_run:
                                    syncset_to_be_created = {
                                        "kind": "SyncSet",
                                        "id": "ext-dynatrace-tokens",
                                        "resources": [
                                            {
                                                "apiVersion": "v1",
                                                "kind": "Secret",
                                                "metadata": {
                                                    "name": "dynatrace-ingestion-token"
                                                },
                                                "data": {
                                                    "id": f"{ingestion_token.id}",
                                                    "token": "ingestion_token.token",
                                                },
                                            },
                                            {
                                                "apiVersion": "v1",
                                                "kind": "Secret",
                                                "namespace": "dynatrace",
                                                "metadata": {
                                                    "name": "dynatrace-operator-token"
                                                },
                                                "data": {
                                                    "id": f"{operator_token.id}",
                                                    "token": "operator_token.token",
                                                },
                                            },
                                        ],
                                    }
                                else:
                                    logging.info("Would have constructed SyncSet")
                            if not dry_run:
                                try:
                                    ocm_client.post(syncset_path, syncset_to_be_created)
                                    logging.info(f"Created SyncSet {SyncSet_ID}")
                                except Exception as e:
                                    _expose_errors_as_service_log(
                                        ocm_client,
                                        cluster.ocm_cluster.external_id,
                                        str(e.args),
                                    )
                                    unhandled_exceptions.append(
                                        f"{env}/{cluster.organization_id}: {e}"
                                    )
                            else:
                                logging.info(f"Would have created SyncSet {SyncSet_ID}")

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)
        sys.exit(0)

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(gql.get_api().query).environments

    def create_dynatrace_ingestion_token(
        self, dt_client: Dynatrace, cluster_uuid: str
    ) -> ApiTokenCreated:
        return dt_client.tokens.create(
            name=f"ingestion-token-{cluster_uuid}",
            scopes=["metrics.ingest", "logs.ingest", "events.ingest"],
        )

    def create_dynatrace_operator_token(
        self, dt_client: Dynatrace, cluster_uuid: str
    ) -> ApiTokenCreated:
        return dt_client.tokens.create(
            name=f"operator-token-{cluster_uuid}",
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


def dtp_label_key(config_atom: str) -> str:
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
