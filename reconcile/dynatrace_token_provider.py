import sys
from datetime import timedelta
from typing import Optional

from dynatrace import Dynatrace

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import (
    gql,
    metrics,
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


class DynatraceTokenProviderIntegrationParams(PydanticRunParams):
    ocm_organization_ids: Optional[set[str]] = None


class ReconcileErrorSummary(Exception):
    def __init__(self, exceptions: list[str]) -> None:
        self.exceptions = exceptions

    def __str__(self) -> str:
        formatted_exceptions = "\n".join([f"- {e}" for e in self.exceptions])
        return f"Reconcile exceptions:\n{ formatted_exceptions }"


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
                    if cluster.labels:
                        dt_tenant_id = cluster.labels.get_label_value(
                            f"{dtp_label_key()}.tenant"
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

                        syncset_path = (
                            cluster.ocm_cluster.external_configuration.syncsets["href"]
                        )

                        try:
                            existing_syncsets = ocm_client.get(syncset_path)
                        except Exception as e:
                            _expose_errors_as_service_log(ocm_client, str(e.args))

                        ingestion_token = None
                        operator_token = None
                        if existing_syncsets["size"] > 0:
                            dt_token_syncset_exist = False
                            for existing_syncset in existing_syncsets["items"]:
                                if existing_syncset["id"] == "ext-dynatrace-tokens":
                                    dt_token_syncset_exist = True
                                    for resource in existing_syncset["resources"]:
                                        if resource["kind"] == "Secret":
                                            token_id = resource["data"]["id"]
                                            try:
                                                dt_client.tokens.get(token_id)
                                            except Exception as e:
                                                if "does not exist" in e.args[0]:
                                                    if (
                                                        "ingestion"
                                                        in resource["metadata"]["name"]
                                                    ):
                                                        ingestion_token = self.create_dynatrace_ingestion_token(
                                                            dt_client,
                                                            cluster.ocm_cluster.external_id,
                                                        )
                                                    elif (
                                                        "operator"
                                                        in resource["metadata"]["name"]
                                                    ):
                                                        operator_token = self.create_dynatrace_operator_token(
                                                            dt_client,
                                                            cluster.ocm_cluster.external_id,
                                                        )
                            if dt_token_syncset_exist:
                                (
                                    ingestion_token,
                                    operator_token,
                                ) = self.create_dynatrace_tokens(
                                    dt_client, cluster.ocm_cluster.external_id
                                )
                        else:
                            (
                                ingestion_token,
                                operator_token,
                            ) = self.create_dynatrace_tokens(
                                dt_client, cluster.ocm_cluster.external_id
                            )

                        if ingestion_token and operator_token:
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
                                            "id": "ingestion_token.id",
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
                                            "id": "operator_token.id",
                                            "token": "operator_token.token",
                                        },
                                    },
                                ],
                            }
                        result = ocm_client.post(syncset_path, syncset_to_be_created)

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)
        sys.exit(0)

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(gql.get_api().query).environments

    def create_dynatrace_ingestion_token(self, dt_client, cluster_uuid):
        return dt_client.tokens.create(
            name=f"ingestion-token-{cluster_uuid}",
            scopes=["metrics.ingest", "logs.ingest", "events.ingest"],
        )

    def create_dynatrace_operator_token(self, dt_client, cluster_uuid):
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

    def create_dynatrace_tokens(self, dt_client, cluster_uuid):
        ingestion_token = self.create_dynatrace_ingestion_token(
            self, dt_client, cluster_uuid
        )
        operation_token = self.create_dynatrace_operator_token(
            self, dt_client, cluster_uuid
        )
        return (ingestion_token, operation_token)


def dtp_label_key(config_atom: str = None) -> str:
    return sre_capability_label_key("dtp", config_atom)


def _expose_errors_as_service_log(
    ocm_api: OCMBaseClient, cluster_uuid: str, error: str
) -> None:
    """
    Highlight cluster upgrade policy validation errors to the cluster
    owners via OCM service logs.
    """
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
