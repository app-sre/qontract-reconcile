from collections.abc import Callable

from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.rhidp.ocm_oidc_idp.integration import (
    OCMOidcIdpIntegration,
    OCMOidcIdpIntegrationParams,
)


def test_ocm_oidc_idp_integration_get_clusters(
    cluster_query_func: Callable, clusters_to_act_on: list[ClusterV1]
) -> None:
    intg = OCMOidcIdpIntegration(
        OCMOidcIdpIntegrationParams(
            vault_input_path="foo/bar", default_auth_issuer_url="https://issuer.com"
        )
    )
    assert intg.get_clusters(cluster_query_func) == clusters_to_act_on
