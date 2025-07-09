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
from reconcile.utils.secret_reader import SecretReaderBase


def test_no_change_hcp_cluster(
    secret_reader: SecretReaderBase,
    default_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_operator_token: DynatraceAPIToken,
    default_ingestion_token: DynatraceAPIToken,
    default_hcp_cluster: OCMCluster,
    default_integration: DynatraceTokenProviderIntegration,
) -> None:
    """
    We have a HCP cluster with an existing manifest and tokens.
    The token ids match with the token ids in Dynatrace.
    We expect no changes.
    """
    tenant_id = default_hcp_cluster.labels[DTP_TENANT_V2_LABEL]
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[default_hcp_cluster],
        get_syncset={},
        get_manifest={
            default_hcp_cluster.id: build_manifest(
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
            )
        },
    )

    ocm_client_by_env_name = {
        "ocm_env_a": ocm_client,
    }

    dynatrace_client = build_dynatrace_client(
        create_api_token={},
        existing_token_ids={
            default_ingestion_token.id: default_ingestion_token.name,
            default_operator_token.id: default_operator_token.name,
        },
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
    ocm_client.create_manifest.assert_not_called()
    dynatrace_client.create_api_token.assert_not_called()
