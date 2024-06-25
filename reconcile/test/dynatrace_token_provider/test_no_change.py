from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
    DynatraceTokenProviderIntegrationParams,
)
from reconcile.dynatrace_token_provider.ocm import Cluster
from reconcile.test.dynatrace_token_provider.fixtures import (
    build_dynatrace_client,
    build_ocm_client,
    build_syncset,
)
from reconcile.utils.dynatrace.client import DynatraceAPITokenCreated
from reconcile.utils.secret_reader import SecretReaderBase


def test_no_change(secret_reader: SecretReaderBase) -> None:
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
    )

    given_clusters = [cluster]

    ocm_client = build_ocm_client(
        discover_clusters_by_labels=given_clusters,
        get_syncset={
            cluster.id: build_syncset(
                operator_token=DynatraceAPITokenCreated(token="operator123", id="id2"),
                ingestion_token=DynatraceAPITokenCreated(token="ingest123", id="id1"),
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
    )

    integration.reconcile(dry_run=False, dependencies=dependencies)

    ocm_client.patch_syncset.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.create_syncset.assert_not_called()  # type: ignore[attr-defined]
    dynatrace_client.create_api_token.assert_not_called()  # type: ignore[attr-defined]
