from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.rhidp.common import Cluster
from reconcile.rhidp.sso_client.base import (
    act,
    console_url_to_oauth_url,
    create_sso_client,
    delete_sso_client,
    fetch_current_state,
    fetch_desired_state,
)
from reconcile.utils.keycloak import (
    KeycloakAPI,
    KeycloakMap,
    SSOClient,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    "console_url, auth_name, expected",
    [
        # OSD cluster w/o port
        (
            "https://console-openshift-console.apps.cluster-name.lalala-land.com/huhu/la/le/lu",
            "super-dupper-auth",
            "https://oauth-openshift.apps.cluster-name.lalala-land.com/oauth2callback/super-dupper-auth",
        ),
        # OSD cluster with port
        (
            "https://console-openshift-console.apps.cluster-name.lalala-land.com:1234/huhu/la/le/lu",
            "super-dupper-auth",
            "https://oauth-openshift.apps.cluster-name.lalala-land.com:1234/oauth2callback/super-dupper-auth",
        ),
        # ROSA cluster w/o port
        (
            "https://console-openshift-console.apps.rosa.cluster-name.lalala-land.com/huhu/la/le/lu",
            "super-dupper-auth",
            "https://oauth.cluster-name.lalala-land.com:443/oauth2callback/super-dupper-auth",
        ),
        # ROSA cluster with port
        (
            "https://console-openshift-console.apps.rosa.cluster-name.lalala-land.com:1234/huhu/la/le/lu",
            "super-dupper-auth",
            "https://oauth.cluster-name.lalala-land.com:1234/oauth2callback/super-dupper-auth",
        ),
    ],
)
def test_sso_client_console_url_to_oauth_url_osd(
    console_url: str, auth_name: str, expected: str
) -> None:
    assert console_url_to_oauth_url(console_url, auth_name) == expected


def test_sso_client_fetch_current_state(secret_reader: Mock) -> None:
    secret_reader.vault_client.list.return_value = ["id-cluster-1", "id-cluster-2"]
    assert fetch_current_state(secret_reader, "vault-input-path") == [
        "id-cluster-1",
        "id-cluster-2",
    ]
    secret_reader.vault_client.list.assert_called_once_with("vault-input-path")


def test_sso_client_fetch_desired_state(clusters: Sequence[Cluster]) -> None:
    assert fetch_desired_state(clusters) == {
        "cluster-1-org-id-1-oidc-auth-issuer.com": clusters[0],
        "cluster-2-org-id-2-oidc-auth-issuer.com": clusters[1],
        "cluster-groups-org-id-2-oidc-auth-issuer.com": clusters[2],
    }


def test_sso_client_act(mocker: MockerFixture, clusters: Sequence[Cluster]) -> None:
    delete_sso_client_mock = mocker.patch(
        "reconcile.rhidp.sso_client.base.delete_sso_client"
    )
    create_sso_client_mock = mocker.patch(
        "reconcile.rhidp.sso_client.base.create_sso_client"
    )
    existing_sso_client_ids = ["to-be-removed", "to-be-kept"]
    desired_sso_clients = {
        "to-be-kept": clusters[0],
        "new-one": clusters[1],
    }

    # dry-run
    act(
        keycloak_map=None,  # type: ignore
        secret_reader=None,  # type: ignore
        vault_input_path="vault-input-path",
        existing_sso_client_ids=existing_sso_client_ids,
        desired_sso_clients=desired_sso_clients,
        dry_run=True,
    )
    create_sso_client_mock.assert_not_called()
    delete_sso_client_mock.assert_not_called()

    # non dry-run
    act(
        keycloak_map=None,  # type: ignore
        secret_reader=None,  # type: ignore
        vault_input_path="vault-input-path",
        existing_sso_client_ids=existing_sso_client_ids,
        desired_sso_clients=desired_sso_clients,
        dry_run=False,
    )
    delete_sso_client_mock.assert_called_once_with(
        keycloak_map=None,
        sso_client_id="to-be-removed",
        secret_reader=None,
        vault_input_path="vault-input-path",
    )
    create_sso_client_mock.assert_called_once_with(
        keycloak_map=None,
        sso_client_id="new-one",
        cluster=clusters[1],
        secret_reader=None,
        vault_input_path="vault-input-path",
    )


@pytest.mark.parametrize(
    "cluster_index, expected_group_filter_regex",
    [
        (0, None),
        (2, "^ai-.*"),
    ],
)
def test_sso_client_create_sso_client(
    mocker: MockerFixture,
    secret_reader: Mock,
    clusters: Sequence[Cluster],
    cluster_index: int,
    expected_group_filter_regex: str | None,
) -> None:
    cluster = clusters[cluster_index]

    sso_client_id = "new-one-foo-bar-org-id-what-ever"
    redirect_uris = ["https://console.foobar.com/oauth2callback/oidc-auth"]
    vault_input_path = "vault-input-path"
    secret = VaultSecret(
        path=f"{vault_input_path}/{sso_client_id}",
        field="field",
        version=None,
        format=None,
    )
    sso_client = SSOClient(
        client_id="uid-1",
        client_name=sso_client_id,
        client_secret="secret-1",
        redirect_uris=redirect_uris,
        registration_access_token="foobar-tken",
        registration_client_uri="https://client-uri.com",
        issuer=cluster.auth.issuer,
    )
    keycloak_map_mock = mocker.create_autospec(KeycloakMap)
    keycloak_api_mock = mocker.create_autospec(KeycloakAPI)
    keycloak_map_mock.get.return_value = keycloak_api_mock
    keycloak_api_mock.register_client.return_value = sso_client

    create_sso_client(
        keycloak_map=keycloak_map_mock,
        sso_client_id=sso_client_id,
        cluster=cluster,
        secret_reader=secret_reader,
        vault_input_path=vault_input_path,
    )

    keycloak_map_mock.get.assert_called_once_with("https://issuer.com")
    keycloak_api_mock.register_client.assert_called_once_with(
        client_name=sso_client_id,
        redirect_uris=redirect_uris,
        group_filter_regex=expected_group_filter_regex,
    )

    secret_reader.vault_client.write.assert_called_once_with(
        secret={
            "path": secret.path,
            "data": sso_client.model_dump(),
        },
        decode_base64=False,
    )


def test_sso_client_delete_sso_client(
    mocker: MockerFixture, secret_reader: Mock
) -> None:
    sso_client_id = "new-one-foo-bar-org-id-what-ever"
    vault_input_path = "vault-input-path"
    issuer = "https://issuer.com"

    secret = VaultSecret(
        path=f"{vault_input_path}/{sso_client_id}",
        field="field",
        version=None,
        format=None,
    )
    sso_client_data = {
        "client_id": "",
        "client_name": sso_client_id,
        "client_secret": "",
        "redirect_uris": [],
        "registration_access_token": "foobar-tken",
        "registration_client_uri": "https://client-uri.com",
        "issuer": issuer,
    }

    keycloak_map_mock = mocker.create_autospec(KeycloakMap)
    keycloak_api_mock = mocker.create_autospec(KeycloakAPI)
    keycloak_map_mock.get.return_value = keycloak_api_mock
    secret_reader.read_all_secret.return_value = sso_client_data

    delete_sso_client(
        keycloak_map=keycloak_map_mock,
        sso_client_id=sso_client_id,
        secret_reader=secret_reader,
        vault_input_path=vault_input_path,
    )

    keycloak_map_mock.get.assert_called_once_with("https://issuer.com")
    keycloak_api_mock.delete_client.assert_called_once_with(
        registration_client_uri=sso_client_data["registration_client_uri"],
        registration_access_token=sso_client_data["registration_access_token"],
    )

    secret_reader.vault_client.delete.assert_called_once_with(path=secret.path)
