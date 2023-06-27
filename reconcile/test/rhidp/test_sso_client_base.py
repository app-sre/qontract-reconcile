from collections.abc import Sequence
from unittest.mock import Mock

from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.rhidp.clusters import (
    ClusterAuthOIDCV1,
    ClusterV1,
)
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


def test_sso_client_console_url_to_oauth_url() -> None:
    assert (
        console_url_to_oauth_url(
            "https://console-openshift-console.foo.bar.lalala-land.com:1234/huhu/la/le/lu",
            "super-dupper-auth",
        )
        == "https://oauth-openshift.foo.bar.lalala-land.com:1234/oauth2callback/super-dupper-auth"
    )


def test_sso_client_fetch_current_state(secret_reader: Mock) -> None:
    secret_reader.vault_client.list.return_value = ["id-cluster-1", "id-cluster-2"]
    assert fetch_current_state(secret_reader, "vault-input-path") == [
        "id-cluster-1",
        "id-cluster-2",
    ]
    secret_reader.vault_client.list.assert_called_once_with("vault-input-path")


def test_sso_client_fetch_desired_state(clusters: Sequence[ClusterV1]) -> None:
    assert fetch_desired_state(clusters) == {
        "cluster-1-org-id-oidc-auth": (clusters[0], clusters[0].auth[0]),
        "cluster-2-org-id-oidc-auth": (clusters[1], clusters[1].auth[0]),
        "cluster-3-org-id-oidc-auth-1": (clusters[2], clusters[2].auth[0]),
        "cluster-3-org-id-oidc-auth-2": (clusters[2], clusters[2].auth[1]),
    }


def test_sso_client_act(mocker: MockerFixture, clusters: Sequence[ClusterV1]) -> None:
    delete_sso_client_mock = mocker.patch(
        "reconcile.rhidp.sso_client.base.delete_sso_client"
    )
    create_sso_client_mock = mocker.patch(
        "reconcile.rhidp.sso_client.base.create_sso_client"
    )
    existing_sso_client_ids = ["to-be-removed", "to-be-kept"]
    desired_sso_clients = {
        "to-be-kept": (clusters[0], clusters[0].auth[0]),
        "new-one": (clusters[1], clusters[1].auth[0]),
    }
    contacts = ["contact-1", "contact-2"]

    # dry-run
    act(
        keycloak_map=None,  # type: ignore
        secret_reader=None,  # type: ignore
        vault_input_path="vault-input-path",
        existing_sso_client_ids=existing_sso_client_ids,
        desired_sso_clients=desired_sso_clients,  # type: ignore
        contacts=contacts,
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
        desired_sso_clients=desired_sso_clients,  # type: ignore
        contacts=contacts,
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
        auth=clusters[1].auth[0],
        contacts=contacts,
        secret_reader=None,
        vault_input_path="vault-input-path",
    )


def test_sso_client_create_sso_client(
    mocker: MockerFixture, secret_reader: Mock, clusters: Sequence[ClusterV1]
) -> None:
    cluster = clusters[0]
    auth = cluster.auth[0]
    if not isinstance(auth, ClusterAuthOIDCV1):
        # just macke mypy happy
        raise ValueError("auth is not OIDCAuthentication")

    SSO_CLIENT_ID = "new-one-foo-bar-org-id-what-ever"
    REDIRECT_URIS = ["https://console.url.com/oauth2callback/oidc-auth"]
    REQUEST_URIS = [cluster.console_url]
    CONTACTS = ["contact-1", "contact-2"]
    VAULT_INPUT_PATH = "vault-input-path"
    secret = VaultSecret(
        path=f"{VAULT_INPUT_PATH}/{SSO_CLIENT_ID}",
        field="field",
        version=None,
        format=None,
    )
    sso_client = SSOClient(
        client_id="uid-1",
        client_id_issued_at=0,
        client_name=SSO_CLIENT_ID,
        client_secret="secret-1",
        client_secret_expires_at=0,
        grant_types=["foobar"],
        redirect_uris=REDIRECT_URIS,
        request_uris=REQUEST_URIS,
        registration_access_token="foobar-tken",
        registration_client_uri="https://client-uri.com",
        response_types=["foobar"],
        subject_type="foobar",
        tls_client_certificate_bound_access_tokens=False,
        token_endpoint_auth_method="foobar",
        issuer=auth.issuer,
    )
    keycloak_map_mock = mocker.create_autospec(KeycloakMap)
    keycloak_api_mock = mocker.create_autospec(KeycloakAPI)
    keycloak_map_mock.get.return_value = keycloak_api_mock
    keycloak_api_mock.register_client.return_value = sso_client

    create_sso_client(
        keycloak_map=keycloak_map_mock,
        sso_client_id=SSO_CLIENT_ID,
        cluster=cluster,
        auth=auth,
        contacts=CONTACTS,
        secret_reader=secret_reader,
        vault_input_path=VAULT_INPUT_PATH,
    )

    keycloak_map_mock.get.assert_called_once_with("https://issuer.com")
    keycloak_api_mock.register_client.assert_called_once_with(
        client_name=SSO_CLIENT_ID,
        redirect_uris=REDIRECT_URIS,
        initiate_login_uri=cluster.console_url,
        request_uris=REQUEST_URIS,
        contacts=CONTACTS,
    )

    secret_reader.vault_client.write.assert_called_once_with(
        secret={
            "path": secret.path,
            "data": sso_client.dict(),
        },
        decode_base64=False,
    )


def test_sso_client_delete_sso_client(
    mocker: MockerFixture, secret_reader: Mock
) -> None:
    SSO_CLIENT_ID = "new-one-foo-bar-org-id-what-ever"
    VAULT_INPUT_PATH = "vault-input-path"
    ISSUER = "https://issuer.com"

    secret = VaultSecret(
        path=f"{VAULT_INPUT_PATH}/{SSO_CLIENT_ID}",
        field="field",
        version=None,
        format=None,
    )
    sso_client_data = {
        "client_id": "",
        "client_id_issued_at": 0,
        "client_name": SSO_CLIENT_ID,
        "client_secret": "",
        "client_secret_expires_at": 0,
        "grant_types": [],
        "redirect_uris": [],
        "request_uris": [],
        "registration_access_token": "foobar-tken",
        "registration_client_uri": "https://client-uri.com",
        "response_types": [],
        "subject_type": "",
        "tls_client_certificate_bound_access_tokens": False,
        "token_endpoint_auth_method": "",
        "issuer": ISSUER,
    }

    keycloak_map_mock = mocker.create_autospec(KeycloakMap)
    keycloak_api_mock = mocker.create_autospec(KeycloakAPI)
    keycloak_map_mock.get.return_value = keycloak_api_mock
    secret_reader.read_all_secret.return_value = sso_client_data

    delete_sso_client(
        keycloak_map=keycloak_map_mock,
        sso_client_id=SSO_CLIENT_ID,
        secret_reader=secret_reader,
        vault_input_path=VAULT_INPUT_PATH,
    )

    keycloak_map_mock.get.assert_called_once_with("https://issuer.com")
    keycloak_api_mock.delete_client.assert_called_once_with(
        registration_client_uri=sso_client_data["registration_client_uri"],
        registration_access_token=sso_client_data["registration_access_token"],
    )

    secret_reader.vault_client.delete.assert_called_once_with(path=secret.path)
