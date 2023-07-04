from collections.abc import Iterable
from unittest.mock import Mock

import pytest

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
    secret_reader.read_all_secret.return_value = {
        "client_id": "just-garbage",
        "client_id_issued_at": 0,
        "client_name": "just-garbage",
        "client_secret": "just-garbage",
        "client_secret_expires_at": 0,
        "grant_types": ["just-garbage"],
        "redirect_uris": ["just-garbage"],
        "registration_access_token": "just-garbage",
        "registration_client_uri": "just-garbage",
        "request_uris": ["just-garbage"],
        "response_types": ["just-garbage"],
        "subject_type": "just-garbage",
        "tls_client_certificate_bound_access_tokens": False,
        "token_endpoint_auth_method": "just-garbage",
        "issuer": "just-garbage",
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
        OCMOidcIdp(
            id=None,
            cluster="cluster-3",
            name="oidc-auth-1",
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
            cluster="cluster-3",
            name="oidc-auth-2",
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
    MANAGED_OIDC_NAME = "oidc-auth"
    idp_in_sync = OCMOidcIdp(
        id="idp-id-cluster-1",
        cluster="cluster-1",
        name=MANAGED_OIDC_NAME,
        client_id="client-id-cluster-1",
        client_secret=None,
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    idp_to_be_removed = OCMOidcIdp(
        id="idp-id-cluster-2",
        cluster="cluster-2",
        name=MANAGED_OIDC_NAME,
        client_id="client-id-cluster-2",
        client_secret=None,
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    idp_to_be_ignored = OCMOidcIdp(
        id="idp-id-cluster-2",
        cluster="cluster-2",
        name="manually-configured-idp",
        client_id="client-id-cluster-2",
        client_secret=None,
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    idp_to_be_changed = OCMOidcIdp(
        id="idp-id-cluster-3",
        cluster="cluster-3",
        name=MANAGED_OIDC_NAME,
        client_id="client-id-cluster-2",
        client_secret=None,
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )
    idp_to_be_added = OCMOidcIdp(
        id=None,
        cluster="cluster-4",
        name=MANAGED_OIDC_NAME,
        client_id="client-id",
        client_secret="client-secret",
        issuer="https://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=[],
    )

    current_state = [
        idp_in_sync,
        idp_to_be_removed,
        idp_to_be_changed,
        idp_to_be_ignored,
    ]
    idp_to_be_changed_copy = idp_to_be_changed.copy(deep=True)
    idp_to_be_changed_copy.username_claims = ["username", "preferred_username"]
    desired_state = [idp_in_sync, idp_to_be_added, idp_to_be_changed_copy]

    # dry-run
    act(
        dry_run=True,
        ocm_map=ocm_map,
        current_state=current_state,
        desired_state=desired_state,
        managed_idps=[MANAGED_OIDC_NAME],
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
        managed_idps=[MANAGED_OIDC_NAME],
    )
    ocm = ocm_map.get.return_value
    ocm.create_oidc_idp.assert_called_once_with(idp_to_be_added)
    ocm.delete_idp.assert_called_once_with(
        idp_to_be_removed.cluster, idp_to_be_removed.id
    )
    ocm.update_oidc_idp.assert_called_once_with(
        idp_to_be_changed.id, idp_to_be_changed_copy
    )


def test_ocm_oidc_idp_act_issuer_change_not_allowed(ocm_map: Mock) -> None:
    test_cluster = OCMOidcIdp(
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

    current_state = [test_cluster]
    test_cluster_copy = test_cluster.copy(deep=True)
    test_cluster_copy.issuer = "http://some-other-issuer.com"
    desired_state = [test_cluster_copy]

    with pytest.raises(ValueError):
        act(
            dry_run=True,
            ocm_map=ocm_map,
            current_state=current_state,
            desired_state=desired_state,
            managed_idps=[],
        )
