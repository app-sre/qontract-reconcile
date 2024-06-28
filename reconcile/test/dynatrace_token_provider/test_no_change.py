from collections.abc import Callable

from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
    DynatraceTokenProviderIntegrationParams,
)
from reconcile.dynatrace_token_provider.model import DynatraceAPIToken, K8sSecret
from reconcile.dynatrace_token_provider.ocm import Cluster
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)
from reconcile.test.dynatrace_token_provider.fixtures import (
    build_dynatrace_client,
    build_ocm_client,
    build_syncset,
)
from reconcile.utils.dynatrace.client import DynatraceAPITokenCreated
from reconcile.utils.secret_reader import SecretReaderBase


def test_no_change(
    secret_reader: SecretReaderBase,
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecV1],
) -> None:
    """
    We have a cluster with an existing syncset and tokens.
    The token ids match with the token ids in Dynatrace.
    We expect no changes.
    """
    integration = DynatraceTokenProviderIntegration(
        DynatraceTokenProviderIntegrationParams(ocm_organization_ids={"ocm_org_id_a"})
    )

    cluster = Cluster(
        id="cluster_a",
        external_id="external_id_a",
        organization_id="ocm_org_id_a",
        dt_tenant="dt_tenant_a",
        token_spec_name="default",
    )

    given_clusters = [cluster]

    ocm_client = build_ocm_client(
        discover_clusters_by_labels=given_clusters,
        get_syncset={
            cluster.id: build_syncset(
                secrets=[
                    K8sSecret(
                        secret_name="dynatrace-token-dtp",
                        namespace_name="dynatrace",
                        tokens=[
                            DynatraceAPIToken(
                                id="id2",
                                name="dtp-operator-token",
                                token="operator123",
                                secret_key="apiToken",
                            ),
                            DynatraceAPIToken(
                                id="id1",
                                name="dtp-ingestion-token",
                                token="ingest123",
                                secret_key="dataIngestToken",
                            ),
                        ],
                    )
                ],
                tenant_id="dt_tenant_a",
                with_id=True,
            )
        },
    )

    ocm_client_by_env_name = {
        "ocm_env_a": ocm_client,
    }

    ingestion_token = DynatraceAPITokenCreated(
        id="id1",
        token="ingest123",
    )

    operator_token = DynatraceAPITokenCreated(
        id="id2",
        token="operator123",
    )

    dynatrace_client = build_dynatrace_client(
        create_api_token={
            f"dtp-ingestion-token-{cluster.external_id}": ingestion_token,
            f"dtp-operator-token-{cluster.external_id}": operator_token,
        },
        existing_token_ids={"id1", "id2"},
    )

    dynatrace_client_by_tenant_id = {
        "dt_tenant_a": dynatrace_client,
    }

    dependencies = Dependencies(
        secret_reader=secret_reader,
        dynatrace_client_by_tenant_id=dynatrace_client_by_tenant_id,
        ocm_client_by_env_name=ocm_client_by_env_name,
        token_spec_by_name={
            "default": gql_class_factory(
                DynatraceTokenProviderTokenSpecV1,
                {
                    "name": "default",
                    "ocm_org_ids": ["ocm_org_id_a"],
                    "secrets": [
                        {
                            "name": "dynatrace-token-dtp",
                            "namespace": "dynatrace",
                            "tokens": [
                                {
                                    "name": "dtp-ingestion-token",
                                    "keyNameInSecret": "dataIngestToken",
                                    "scopes": [
                                        "metrics.ingest",
                                        "logs.ingest",
                                        "events.ingest",
                                    ],
                                },
                                {
                                    "name": "dtp-operator-token",
                                    "keyNameInSecret": "apiToken",
                                    "scopes": [
                                        "activeGateTokenManagement.create",
                                        "entities.read",
                                        "settings.write",
                                        "settings.read",
                                        "DataExport",
                                        "InstallerDownload",
                                    ],
                                },
                            ],
                        }
                    ],
                },
            )
        },
    )

    integration.reconcile(dry_run=False, dependencies=dependencies)

    ocm_client.patch_syncset.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.create_syncset.assert_not_called()  # type: ignore[attr-defined]
    dynatrace_client.create_api_token.assert_not_called()  # type: ignore[attr-defined]
