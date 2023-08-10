import logging
import sys
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
from reconcile.utils.ocm.clusters import discover_clusters_by_labels
from reconcile.utils.ocm.labels import subscription_label_filter
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.ocm_base_client import init_ocm_base_client
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "dynatrace-token-provider"


class ReconcileErrorSummary(Exception):
    def __init__(self, exceptions: list[str]) -> None:
        self.exceptions = exceptions

    def __str__(self) -> str:
        formatted_exceptions = "\n".join([f"- {e}" for e in self.exceptions])
        return f"Reconcile exceptions:\n{ formatted_exceptions }"


class DynatraceTokenProviderIntegration(QontractReconcileIntegration):
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
                        existing_syncsets = ocm_client.get(syncset_path)

                        # TODO: if existing_syncsets contains a expected secret, get the id and see if it exist in Dynatrace
                        # and only create token if it doesn't exist on either side

                        # ingestion_token = dt_client.tokens.create(
                        #     name="ingestion-token",
                        #     scopes=["metrics.ingest", "logs.ingest", "events.ingest"],
                        # )

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

                        syncset_to_be_created = {
                            "kind": "SyncSet",
                            "id": "ext-dynatrace-ingestion-token",
                            "resources": [
                                {
                                    "apiVersion": "v1",
                                    "kind": "Secret",
                                    "metadata": {
                                        "name": "dynatrace-ingestion-token-id"
                                    },
                                    "data": {
                                        "id": "ingestion_token.id",
                                        "token": "ingestion_token.token",
                                    },
                                }
                            ],
                        }
                        #result = ocm_client.post(syncset_path, syncset_to_be_created)

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)
        sys.exit(0)

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(gql.get_api().query).environments


def dtp_label_key(config_atom: str = None) -> str:
    return sre_capability_label_key("dtp", config_atom)
