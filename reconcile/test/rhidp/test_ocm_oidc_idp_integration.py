from typing import Callable

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.rhidp.clusters import (
    ClusterAuthOIDCClaimsV1,
    ClusterAuthOIDCV1,
    ClusterAuthV1,
    ClusterV1,
    OpenShiftClusterManagerV1,
)
from reconcile.rhidp.ocm_oidc_idp.integration import (
    OCMOidcIdpIntegration,
    OCMOidcIdpIntegrationParams,
)


def test_ocm_oidc_idp_integration_get_clusters(cluster_query_func: Callable) -> None:
    intg = OCMOidcIdpIntegration(
        OCMOidcIdpIntegrationParams(
            vault_input_path="foo/bar", default_auth_issuer_url="https://issuer.com"
        )
    )
    assert intg.get_clusters(cluster_query_func) == [
        ClusterV1(
            name="cluster-1",
            consoleUrl="https://console.url.com",
            ocm=OpenShiftClusterManagerV1(
                name="ocm-production",
                accessTokenClientId=None,
                accessTokenUrl=None,
                accessTokenClientSecret=None,
                environment=OCMEnvironment(
                    name="name",
                    url="https://api.openshift.com",
                    accessTokenClientId="access-token-client-id",
                    accessTokenUrl="http://token-url.com",
                    accessTokenClientSecret=VaultSecret(
                        field="client_secret",
                        format=None,
                        path="path/to/client_secret",
                        version=None,
                    ),
                ),
                orgId="org-id",
                blockedVersions=[],
                sectors=None,
            ),
            upgradePolicy=None,
            disable=None,
            auth=[
                ClusterAuthOIDCV1(
                    service="oidc",
                    name="oidc-auth",
                    issuer="https://issuer.com",
                    claims=ClusterAuthOIDCClaimsV1(
                        email=["email"],
                        name=["name"],
                        username=["username"],
                        groups=None,
                    ),
                )
            ],
        ),
        ClusterV1(
            name="cluster-2",
            consoleUrl="https://console.url.com",
            ocm=OpenShiftClusterManagerV1(
                name="ocm-production",
                accessTokenClientId=None,
                accessTokenUrl=None,
                accessTokenClientSecret=None,
                environment=OCMEnvironment(
                    name="name",
                    url="https://api.openshift.com",
                    accessTokenClientId="access-token-client-id",
                    accessTokenUrl="http://token-url.com",
                    accessTokenClientSecret=VaultSecret(
                        field="client_secret",
                        format=None,
                        path="path/to/client_secret",
                        version=None,
                    ),
                ),
                orgId="org-id",
                blockedVersions=[],
                sectors=None,
            ),
            upgradePolicy=None,
            disable=None,
            auth=[
                ClusterAuthV1(service="github-org-team"),
                ClusterAuthOIDCV1(
                    service="oidc",
                    name="oidc-auth",
                    issuer="https://issuer.com",
                    claims=ClusterAuthOIDCClaimsV1(
                        email=["email"],
                        name=["name"],
                        username=["username"],
                        groups=None,
                    ),
                ),
            ],
        ),
    ]
