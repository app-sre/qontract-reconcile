from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
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
from reconcile.utils.secret_reader import SecretReaderBase


def test_spec_to_existing_token_diff(
    secret_reader: SecretReaderBase,
    default_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_operator_token: DynatraceAPIToken,
    default_ingestion_token: DynatraceAPIToken,
    default_cluster: Cluster,
    default_integration: DynatraceTokenProviderIntegration,
) -> None:
    """
    We have an existing token in Dynatrace that does not match the spec.
    We expect DTP to update the token to match the given spec.
    """
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
                            default_ingestion_token,
                            default_operator_token,
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

    dynatrace_client = build_dynatrace_client(
        create_api_token={},
        # Operator token name indicates that the spec doesnt match the token config.
        # Ingestion token matches the token spec.
        existing_token_ids={
            default_ingestion_token.id: "dtp_ingestion-token_external_id_a_f6e7fac64719",
            default_operator_token.id: "config-diff",
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

    ocm_client.create_syncset.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.create_manifest.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.patch_manifest.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.patch_syncset.assert_not_called()  # type: ignore[attr-defined]
    dynatrace_client.create_api_token.assert_not_called()  # type: ignore[attr-defined]
    dynatrace_client.update_token.assert_called_once_with(  # type: ignore[attr-defined]
        name="dtp_operator-token_external_id_a_1b6c3b9a7248",
        scopes=[
            "activeGateTokenManagement.create",
            "entities.read",
            "settings.write",
            "settings.read",
            "DataExport",
            "InstallerDownload",
        ],
        token_id=default_operator_token.id,
    )
