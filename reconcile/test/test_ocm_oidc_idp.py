from collections.abc import (
    Iterable,
    Sequence,
)
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile import ocm_oidc_idp
from reconcile.gql_definitions.ocm_oidc_idp.clusters import (
    ClusterAuthOIDCClaimsV1,
    ClusterAuthOIDCV1,
    ClusterAuthV1,
    ClusterV1,
    OpenShiftClusterManagerV1,
)
from reconcile.ocm.types import OCMOidcIdp
from reconcile.test.fixtures import Fixtures
from reconcile.utils.ocm import OCMMap


@pytest.fixture
def fx():
    return Fixtures("ocm_oidc_idp")


@pytest.fixture
def clusters(fx: Fixtures) -> list[ClusterV1]:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fx.get_anymarkup("clusters.yml")

    return ocm_oidc_idp.get_clusters(q)


@pytest.fixture
def ocm_map(mocker: MockerFixture, fx: Fixtures) -> Mock:
    ocm_map_mock = mocker.create_autospec(OCMMap)
    side_effects = []
    for result in fx.get_anymarkup("get_oidc_idps.yml"):
        side_effects.append([OCMOidcIdp(**i) for i in result])
    ocm_map_mock.get.return_value.get_oidc_idps.side_effect = side_effects
    return ocm_map_mock


def test_ocm_oidc_idp_get_clusters(clusters: Sequence[ClusterV1]):
    assert len(clusters) == 3
    assert clusters == [
        ClusterV1(
            name="cluster-1",
            ocm=OpenShiftClusterManagerV1(
                name="ocm-production",
                url="https://api.openshift.com",
                accessTokenClientId="access-token-client-id",
                accessTokenUrl="http://token-url.com",
                accessTokenClientSecret=None,
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
            ocm=OpenShiftClusterManagerV1(
                name="ocm-production",
                url="https://api.openshift.com",
                accessTokenClientId="access-token-client-id",
                accessTokenUrl="http://token-url.com",
                accessTokenClientSecret=None,
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
        ClusterV1(
            name="cluster-3",
            ocm=OpenShiftClusterManagerV1(
                name="ocm-production",
                url="https://api.openshift.com",
                accessTokenClientId="access-token-client-id",
                accessTokenUrl="http://token-url.com",
                accessTokenClientSecret=None,
                blockedVersions=[],
                sectors=None,
            ),
            upgradePolicy=None,
            disable=None,
            auth=[ClusterAuthV1(service="github-org-team")],
        ),
    ]


def test_ocm_oidc_idp_fetch_current_state(ocm_map: Mock, clusters: Iterable[ClusterV1]):
    current_state = ocm_oidc_idp.fetch_current_state(ocm_map, clusters)
    assert current_state == [
        OCMOidcIdp(
            id="idp-id-cluster-1",
            cluster="cluster-1",
            name="oidc-auth",
            client_id="client-id-cluster-1",
            client_secret=None,
            issuer="https://issuer.com",
            email_claims=["email"],
            name_claims=["name"],
            username_claims=["username"],
            groups_claims=[],
        ),
        OCMOidcIdp(
            id="idp-id-cluster-2",
            cluster="cluster-2",
            name="oidc-auth",
            client_id="client-id-cluster-2",
            client_secret=None,
            issuer="https://issuer.com",
            email_claims=["email"],
            name_claims=["name"],
            username_claims=["username"],
            groups_claims=[],
        ),
    ]


def test_ocm_oidc_idp_fetch_desired_state(
    secret_reader: Mock, clusters: Iterable[ClusterV1]
):
    secret_reader.read_all.return_value = {
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    desired_state = ocm_oidc_idp.fetch_desired_state(
        secret_reader, clusters, vault_input_path="foo/bar"
    )
    assert desired_state == [
        OCMOidcIdp(
            id=None,
            cluster="cluster-1",
            name="oidc-auth",
            client_id="client-id",
            client_secret="client-secret",
            issuer="https://issuer.com",
            email_claims=["email"],
            name_claims=["name"],
            username_claims=["username"],
            groups_claims=[],
        ),
        OCMOidcIdp(
            id=None,
            cluster="cluster-2",
            name="oidc-auth",
            client_id="client-id",
            client_secret="client-secret",
            issuer="https://issuer.com",
            email_claims=["email"],
            name_claims=["name"],
            username_claims=["username"],
            groups_claims=[],
        ),
    ]


def test_ocm_oidc_idp_act(ocm_map: Mock):
    cluster_in_sync = OCMOidcIdp(
        id="idp-id-cluster-1",
        cluster="cluster-1",
        name="oidc-auth",
        client_id="client-id-cluster-1",
        client_secret=None,
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    cluster_to_be_removed = OCMOidcIdp(
        id="idp-id-cluster-2",
        cluster="cluster-2",
        name="oidc-auth",
        client_id="client-id-cluster-2",
        client_secret=None,
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    cluster_to_be_changed = OCMOidcIdp(
        id="idp-id-cluster-3",
        cluster="cluster-3",
        name="oidc-auth",
        client_id="client-id-cluster-2",
        client_secret=None,
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    cluster_to_be_added = OCMOidcIdp(
        id=None,
        cluster="cluster-4",
        name="oidc-auth",
        client_id="client-id",
        client_secret="client-secret",
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    current_state = [cluster_in_sync, cluster_to_be_removed, cluster_to_be_changed]
    cluster_to_be_changed_copy = cluster_to_be_changed.copy(deep=True)
    cluster_to_be_changed_copy.issuer = "http://some-other-issuer.com"
    desired_state = [cluster_in_sync, cluster_to_be_added, cluster_to_be_changed_copy]

    # dry-run
    ocm_oidc_idp.act(
        dry_run=True,
        ocm_map=ocm_map,
        current_state=current_state,
        desired_state=desired_state,
    )
    ocm_map.get.assert_not_called()
    ocm = ocm_map.get.return_value
    ocm.create_oidc_idp.assert_not_called()
    ocm.delete_idp.assert_not_called()
    ocm.update_oidc_idp.assert_not_called()

    # non dry-run
    ocm_oidc_idp.act(
        dry_run=False,
        ocm_map=ocm_map,
        current_state=current_state,
        desired_state=desired_state,
    )
    ocm = ocm_map.get.return_value
    ocm.create_oidc_idp.assert_called_once_with(cluster_to_be_added)
    ocm.delete_idp.assert_called_once_with(
        cluster_to_be_removed.cluster, cluster_to_be_removed.id
    )
    ocm.update_oidc_idp.assert_called_once_with(
        cluster_to_be_changed.id, cluster_to_be_changed_copy
    )
