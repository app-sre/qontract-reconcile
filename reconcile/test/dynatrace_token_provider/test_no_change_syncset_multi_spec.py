from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
)
from reconcile.dynatrace_token_provider.model import DynatraceAPIToken
from reconcile.dynatrace_token_provider.ocm import OCMCluster
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)
from reconcile.test.dynatrace_token_provider.fixtures import (
    REGIONAL_TENANT_KEY,
    SLO_TENANT_KEY,
    build_dynatrace_client,
    build_k8s_secret,
    build_ocm_client,
    build_syncset,
)
from reconcile.utils.secret_reader import SecretReaderBase


def test_no_change_non_hcp_cluster_multi_spec(
    secret_reader: SecretReaderBase,
    slo_token_spec: DynatraceTokenProviderTokenSpecV1,
    regional_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_operator_token: DynatraceAPIToken,
    default_ingestion_token: DynatraceAPIToken,
    default_cluster_v3: OCMCluster,
    default_integration: DynatraceTokenProviderIntegration,
) -> None:
    """
    We have a non-HCP cluster with an existing syncset and tokens.
    The token ids match with the token ids in Dynatrace.
    The cluster has 2 different token specs assigned.
    We expect no changes.
    """
    regional_tenant_id = default_cluster_v3.labels[REGIONAL_TENANT_KEY]
    slo_tenant_id = default_cluster_v3.labels[SLO_TENANT_KEY]
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[default_cluster_v3],
        get_manifest={},
        get_syncset={
            default_cluster_v3.id: build_syncset(
                secrets=[
                    build_k8s_secret(
                        tokens=[
                            default_ingestion_token,
                            default_operator_token,
                        ],
                        secret_name="dynatrace-token-dtp",
                        namespace_name="dynatrace",
                        tenant_id=regional_tenant_id,
                    ),
                    build_k8s_secret(
                        tokens=[
                            default_ingestion_token,
                        ],
                        secret_name="dynatrace-slo-token-dtp",
                        namespace_name="dynatrace",
                        tenant_id=slo_tenant_id,
                    ),
                ],
                with_id=True,
            )
        },
    )

    ocm_client_by_env_name = {
        "ocm_env_a": ocm_client,
    }

    regional_dynatrace_client = build_dynatrace_client(
        create_api_token={},
        existing_token_ids={
            default_ingestion_token.id: default_ingestion_token.name,
            default_operator_token.id: default_operator_token.name,
        },
    )
    slo_dynatrace_client = build_dynatrace_client(
        create_api_token={},
        existing_token_ids={
            default_ingestion_token.id: default_ingestion_token.name,
        },
    )

    dynatrace_client_by_tenant_id = {
        "regional-tenant": regional_dynatrace_client,
        "slo-tenant": slo_dynatrace_client,
    }

    dependencies = Dependencies(
        secret_reader=secret_reader,
        dynatrace_client_by_tenant_id=dynatrace_client_by_tenant_id,
        ocm_client_by_env_name=ocm_client_by_env_name,
        token_spec_by_name={
            "slo-spec": slo_token_spec,
            "regional-spec": regional_token_spec,
        },
    )

    default_integration.reconcile(dry_run=False, dependencies=dependencies)

    ocm_client.patch_syncset.assert_not_called()
    ocm_client.create_syncset.assert_not_called()
    ocm_client.patch_manifest.assert_not_called()
    ocm_client.create_manifest.assert_not_called()
    slo_dynatrace_client.create_api_token.assert_not_called()
    regional_dynatrace_client.create_api_token.assert_not_called()
