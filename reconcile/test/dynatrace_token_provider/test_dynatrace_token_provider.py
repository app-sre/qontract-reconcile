from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
    DynatraceTokenProviderIntegrationParams,
)
from reconcile.dynatrace_token_provider.ocm import Cluster
from reconcile.test.dynatrace_token_provider.fixtures import (
    build_dynatrace_client,
    build_ocm_client,
)
from reconcile.utils.secret_reader import SecretReaderBase


def test_integration(secret_reader: SecretReaderBase) -> None:
    integration = DynatraceTokenProviderIntegration(
        DynatraceTokenProviderIntegrationParams(
            ocm_organization_ids={"ocm_org_id_a", "ocm_org_id_b"}
        )
    )

    # given_clusters = [
    #     Cluster(
    #         id="cluster_a",
    #         external_id="external_id_a",
    #         organization_id="ocm_org_id_a",
    #         dt_tenant="dt_tenant_a",
    #     )
    # ]
    given_clusters: list[Cluster] = []

    ocm_client_by_env_name = {
        "ocm_env_a": build_ocm_client(cluster_details=given_clusters),
    }

    dynatrace_client_by_tenant_id = {
        "dt_tenant_a": build_dynatrace_client(),
    }

    dependencies = Dependencies(
        secret_reader=secret_reader,
        dynatrace_client_by_tenant_id=dynatrace_client_by_tenant_id,
        ocm_client_by_env_name=ocm_client_by_env_name,
    )

    integration.reconcile(dry_run=True, dependencies=dependencies)
