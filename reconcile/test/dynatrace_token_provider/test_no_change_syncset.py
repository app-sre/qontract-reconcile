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


def test_no_change_non_hcp_cluster(
    secret_reader: SecretReaderBase,
    default_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_operator_token: DynatraceAPIToken,
    default_ingestion_token: DynatraceAPIToken,
    default_cluster: Cluster,
) -> None:
    """
    We have a non-HCP cluster with an existing syncset and tokens.
    The token ids match with the token ids in Dynatrace.
    We expect no changes.
    """
    integration = DynatraceTokenProviderIntegration(
        DynatraceTokenProviderIntegrationParams(ocm_organization_ids={"ocm_org_id_a"})
    )

    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[default_cluster],
        get_manifest={},
        get_syncset={
            default_cluster.id: build_syncset(
                secrets=[
                    K8sSecret(
                        secret_name="dynatrace-token-dtp",
                        namespace_name="dynatrace",
                        tokens=[
                            default_operator_token,
                            default_ingestion_token,
                        ],
                    )
                ],
                tenant_id=default_cluster.dt_tenant,
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
        existing_token_ids={default_ingestion_token.id, default_operator_token.id},
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

    integration.reconcile(dry_run=False, dependencies=dependencies)

    ocm_client.patch_syncset.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.create_syncset.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.patch_manifest.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.create_manifest.assert_not_called()  # type: ignore[attr-defined]
    dynatrace_client.create_api_token.assert_not_called()  # type: ignore[attr-defined]
