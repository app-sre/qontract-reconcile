from collections.abc import Callable

from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.rhidp.sso_client.integration import (
    SSOClientIntegration,
    SSOClientIntegrationParams,
)


def test_ocm_oidc_idp_integration_get_clusters(
    cluster_query_func: Callable, clusters_to_act_on: list[ClusterV1]
) -> None:
    intg = SSOClientIntegration(
        SSOClientIntegrationParams(
            keycloak_vault_paths=["foo/bar"],
            vault_input_path="foo/bar",
            default_auth_issuer_url="https://issuer.com",
            contacts=["email@foobar.com"],
        )
    )
    assert intg.get_clusters(cluster_query_func) == clusters_to_act_on
