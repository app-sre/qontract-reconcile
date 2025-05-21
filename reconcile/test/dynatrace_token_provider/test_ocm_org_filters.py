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
    build_dynatrace_client,
    build_k8s_secret,
    build_ocm_client,
    build_syncset,
)
from reconcile.utils.secret_reader import SecretReaderBase


def test_ocm_org_filters(
    secret_reader: SecretReaderBase,
    default_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_operator_token: DynatraceAPIToken,
    default_ingestion_token: DynatraceAPIToken,
    default_integration: DynatraceTokenProviderIntegration,
) -> None:
    """
    We have a cluster that is not part of its spec's ocm org ids.
    There is a diff to desired state (patch + create).
    However, we expect the cluster to be filtered.
    """
    cluster_a = OCMCluster(
        id="cluster_a",
        external_id="external_id_b",
        organization_id="does-not-exist",
        subscription_id="sub_id",
        dt_tenant="dt_tenant_a",
        token_spec_name="default",
        is_hcp=False,
        labels={},
    )
    given_clusters = [cluster_a]
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=given_clusters,
        get_manifest={},
        get_syncset={
            cluster_a.id: build_syncset(
                secrets=[
                    build_k8s_secret(
                        tokens=[
                            default_ingestion_token,
                            default_operator_token,
                        ],
                        tenant_id="dt_tenant_a",
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
        # Operator token id is missing
        existing_token_ids={default_ingestion_token.id: "name1"},
    )

    dynatrace_client_by_tenant_id = {
        "dt_tenant_a": dynatrace_client,
    }

    default_token_spec.ocm_org_ids = ["change"]
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
