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
    build_ocm_client,
    build_syncset,
)
from reconcile.utils.dynatrace.client import DynatraceAPITokenCreated
from reconcile.utils.secret_reader import SecretReaderBase


def test_no_change_non_hcp_cluster(
    secret_reader: SecretReaderBase,
    default_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_operator_token: DynatraceAPIToken,
    default_ingestion_token: DynatraceAPIToken,
    default_cluster: OCMCluster,
    default_integration: DynatraceTokenProviderIntegration,
) -> None:
    """
    We have a non-HCP cluster with an existing syncset and tokens.
    The token ids match with the token ids in Dynatrace.
    We expect no changes.
    """
    tenant_id = default_cluster.labels[DTP_TENANT_V2_LABEL]
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[default_cluster],
        get_manifest={},
        get_syncset={
            default_cluster.id: build_syncset(
                secrets=[
                    build_k8s_secret(
                        tokens=[
                            default_ingestion_token,
                            default_operator_token,
                        ],
                        tenant_id=tenant_id,
                    )
                ],
                tenant_id=tenant_id,
                with_id=True,
            )
        },
    )

    ocm_client_by_env_name = {
        "ocm_env_a": ocm_client,
    }

    ingestion_token = DynatraceAPITokenCreated(
        id=default_ingestion_token.id,
        token=default_ingestion_token.token,
    )

    operator_token = DynatraceAPITokenCreated(
        id=default_operator_token.id,
        token=default_operator_token.token,
    )

    dynatrace_client = build_dynatrace_client(
        create_api_token={
            f"dtp-ingestion-token-{default_cluster.external_id}": ingestion_token,
            f"dtp-operator-token-{default_cluster.external_id}": operator_token,
        },
        existing_token_ids={
            default_ingestion_token.id: "name1",
            default_operator_token.id: "name2",
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
