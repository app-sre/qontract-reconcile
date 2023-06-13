from collections.abc import Iterable
from unittest.mock import Mock

from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.ocm.types import OCMOidcIdp
from reconcile.rhidp.ocm_oidc_idp.base import (
    act,
    fetch_current_state,
    fetch_desired_state,
)


def test_ocm_oidc_idp_fetch_current_state(
    ocm_map: Mock, clusters: Iterable[ClusterV1]
) -> None:
    current_state = fetch_current_state(ocm_map, clusters)
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
) -> None:
    secret_reader.read_all.return_value = {
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    desired_state = fetch_desired_state(
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


def test_ocm_oidc_idp_act(ocm_map: Mock) -> None:
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
    act(
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
    act(
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
