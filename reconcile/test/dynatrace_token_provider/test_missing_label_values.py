from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
)
from reconcile.dynatrace_token_provider.ocm import Cluster
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)
from reconcile.test.dynatrace_token_provider.fixtures import (
    build_dynatrace_client,
    build_ocm_client,
)
from reconcile.utils.secret_reader import SecretReaderBase


def test_missing_all_dtp_label_value(
    secret_reader: SecretReaderBase,
    default_token_spec: DynatraceTokenProviderTokenSpecV1,
    default_integration: DynatraceTokenProviderIntegration,
) -> None:
    """
    We have a cluster that misses values for sre-capabilities.dtp
    and sre-capabilities.dtp.tenant labels.
    There should be no action and no blocking error.
    """
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[
            Cluster(
                id="test_id",
                external_id="test_external_id",
                organization_id="ocm_env_a",
                token_spec_name=None,
                dt_tenant=None,
                is_hcp=False,
            )
        ],
        get_syncset={},
        get_manifest={},
    )

    ocm_client_by_env_name = {
        "ocm_env_a": ocm_client,
    }

    dynatrace_client = build_dynatrace_client(
        create_api_token={},
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

    ocm_client.create_syncset.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.create_manifest.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.patch_syncset.assert_not_called()  # type: ignore[attr-defined]
    dynatrace_client.update_token.assert_not_called()  # type: ignore[attr-defined]
    dynatrace_client.create_api_token.assert_not_called()  # type: ignore[attr-defined]
    ocm_client.patch_manifest.assert_not_called()  # type: ignore[attr-defined]
