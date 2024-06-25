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


def test_single_cluster_create_tokens(secret_reader: SecretReaderBase) -> None:
    """
    We have a single cluster that does not have a syncset/token yet.
    New tokens in a new syncset should be created.
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
        get_syncset={},
    )

    ocm_client_by_env_name = {
        "ocm_env_a": ocm_client,
    }

    operator_token = DynatraceAPITokenCreated(
        id="id1",
        token="ingest123",
    )

    ingestion_token = DynatraceAPITokenCreated(
        id="id2",
        token="operator123",
    )

    dynatrace_client = build_dynatrace_client(
        create_api_token={
            f"dtp-ingestion-token-{cluster.external_id}": ingestion_token,
            f"dtp-operator-token-{cluster.external_id}": operator_token,
        },
        existing_token_ids=set(),
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
    ocm_client.create_syncset.assert_called_once_with(  # type: ignore[attr-defined]
        cluster_id="cluster_a",
        syncset_map=build_syncset(
            operator_token=operator_token,
            ingestion_token=ingestion_token,
            tenant_id="dt_tenant_a",
            with_id=True,
        ),
    )
    assert (
        len(dynatrace_client.create_api_token.mock_calls)  # type: ignore[attr-defined]
        == 2
    )
    dynatrace_client.create_api_token.assert_any_call(  # type: ignore[attr-defined]
        name="dtp-operator-token-external_id_a",
        scopes=[
            "activeGateTokenManagement.create",
            "entities.read",
            "settings.write",
            "settings.read",
            "DataExport",
            "InstallerDownload",
        ],
    )
    dynatrace_client.create_api_token.assert_any_call(  # type: ignore[attr-defined]
        name="dtp-ingestion-token-external_id_a",
        scopes=["metrics.ingest", "logs.ingest", "events.ingest"],
    )
