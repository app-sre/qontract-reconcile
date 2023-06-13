import pytest

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.rhidp.clusters import (
    ClusterAuthOIDCV1,
    ClusterV1,
    OpenShiftClusterManagerV1,
)
from reconcile.rhidp.ocm_oidc_idp import standalone
from reconcile.test.ocm.fixtures import build_cluster_details
from reconcile.utils.ocm.labels import LabelContainer


@pytest.fixture
def ocm_env() -> OCMEnvironment:
    return OCMEnvironment(
        name="env",
        url="https://ocm",
        accessTokenUrl="https://sso/token",
        accessTokenClientId="client-id",
        accessTokenClientSecret=VaultSecret(
            field="client-secret", path="path", format=None, version=None
        ),
    )


def test_ocm_oidc_idp_standalone_build_cluster_obj_for_oidc_auth(
    ocm_env: OCMEnvironment, build_cluster_rhidp_labels: LabelContainer
) -> None:
    cluster_details = build_cluster_details(
        cluster_name="cluster_name",
        subscription_labels=build_cluster_rhidp_labels,
        org_id="org_id",
    )
    assert standalone._build_cluster_obj_for_oidc_auth(
        ocm_env,
        cluster_details,
        auth_name="auth_name",
        auth_issuer_url="https://foobar.com",
    ) == ClusterV1(
        name="cluster_name",
        ocm=OpenShiftClusterManagerV1(
            name="",
            environment=OCMEnvironment(
                name="env",
                url="https://ocm",
                accessTokenClientId="client-id",
                accessTokenUrl="https://sso/token",
                accessTokenClientSecret=VaultSecret(
                    path="path", field="client-secret", version=None, format=None
                ),
            ),
            orgId="org_id",
            accessTokenClientId=None,
            accessTokenUrl=None,
            accessTokenClientSecret=None,
            blockedVersions=None,
            sectors=None,
        ),
        upgradePolicy=None,
        disable=None,
        auth=[
            ClusterAuthOIDCV1(
                service="oidc",
                name="auth_name",
                issuer="https://foobar.com",
                claims=None,
            )
        ],
    )
