from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DTP_TENANT_V2_LABEL,
    DynatraceTokenProviderIntegration,
)
from reconcile.dynatrace_token_provider.model import DynatraceAPIToken
from reconcile.dynatrace_token_provider.ocm import OCMCluster
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)
from reconcile.test.dynatrace_token_provider.fixtures import (
    build_dynatrace_client,
    build_k8s_secret,
    build_manifest,
    build_ocm_client,
)
from reconcile.utils.dynatrace.client import DynatraceAPITokenCreated
from reconcile.utils.secret_reader import SecretReaderBase


def test_single_hcp_cluster_create_tokens(
    secret_reader: SecretReaderBase,
    default_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_operator_token: DynatraceAPIToken,
    default_ingestion_token: DynatraceAPIToken,
    default_hcp_cluster: OCMCluster,
    default_integration: DynatraceTokenProviderIntegration,
) -> None:
    """
    We have a single HCP cluster that does not have a manifest/token yet.
    New tokens in a new manifest should be created.
    """
    tenant_id = default_hcp_cluster.labels[DTP_TENANT_V2_LABEL]
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[default_hcp_cluster],
        get_syncset={},
        get_manifest={},
    )

    ocm_client_by_env_name = {
        "ocm_env_a": ocm_client,
    }

    operator_token = DynatraceAPITokenCreated(
        id=default_operator_token.id,
        token=default_operator_token.token,
    )

    ingestion_token = DynatraceAPITokenCreated(
        id=default_ingestion_token.id,
        token=default_ingestion_token.token,
    )

    dynatrace_client = build_dynatrace_client(
        create_api_token={
            "dtp_ingestion-token_external_id_a_f6e7fac64719": ingestion_token,
            "dtp_operator-token_external_id_a_1b6c3b9a7248": operator_token,
        },
        existing_token_ids={},
    )

    dynatrace_client_by_tenant_id = {
        "dt_tenant_a": dynatrace_client,
    }

    dependencies = Dependencies(
        secret_reader=secret_reader,
        dynatrace_client_by_tenant_id=dynatrace_client_by_tenant_id,
        ocm_client_by_env_name=ocm_client_by_env_name,
        token_spec_by_name={
            "default": default_token_spec,
        },
    )

    default_integration.reconcile(dry_run=False, dependencies=dependencies)

    ocm_client.patch_syncset.assert_not_called()
    ocm_client.create_syncset.assert_not_called()
    ocm_client.patch_manifest.assert_not_called()
    dynatrace_client.update_token.assert_not_called()

    assert len(dynatrace_client.create_api_token.mock_calls) == 2
    dynatrace_client.create_api_token.assert_any_call(
        name="dtp_operator-token_external_id_a_1b6c3b9a7248",
        scopes=[
            "activeGateTokenManagement.create",
            "entities.read",
            "settings.write",
            "settings.read",
            "DataExport",
            "InstallerDownload",
        ],
    )
    dynatrace_client.create_api_token.assert_any_call(
        name="dtp_ingestion-token_external_id_a_f6e7fac64719",
        scopes=["metrics.ingest", "logs.ingest", "events.ingest"],
    )
    ocm_client.create_manifest.assert_called_once_with(
        cluster_id="cluster_a",
        manifest_map=build_manifest(
            secrets=[
                build_k8s_secret(
                    tokens=[
                        default_ingestion_token,
                        default_operator_token,
                    ],
                    tenant_id=tenant_id,
                )
            ],
            with_id=True,
        ),
    )
