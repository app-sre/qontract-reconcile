import logging
from collections.abc import (
    Iterable,
    Sequence,
)
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
)

import jwt

from reconcile.gql_definitions.rhidp.clusters import (
    ClusterAuthOIDCV1,
    ClusterV1,
)
from reconcile.rhidp.common import (
    cluster_vault_secret,
    cluster_vault_secret_id,
    expose_base_metrics,
)
from reconcile.rhidp.sso_client.metrics import (
    RhIdpSSOClientCounter,
    RhIdpSSOClientIatExpiration,
    RhIdpSSOClientReconcileCounter,
    RhIdpSSOClientReconcileErrorCounter,
)
from reconcile.utils import metrics
from reconcile.utils.keycloak import (
    KeycloakInstance,
    KeycloakMap,
    SSOClient,
)
from reconcile.utils.secret_reader import VaultSecretReader

DesiredSSOClients = dict[str, tuple[ClusterV1, ClusterAuthOIDCV1]]


def console_url_to_oauth_url(console_url: str, auth_name: str) -> str:
    """Convert a console URL to an OAuth callback URL."""
    if console_url.startswith("https://console-openshift-console.apps.rosa."):
        # ROSA cluster

        url = urlparse(
            urljoin(
                console_url.replace("console-openshift-console.apps.rosa", "oauth"),
                f"/oauth2callback/{auth_name}",
            )
        )
        if url.port is None:
            url = url._replace(netloc=url.netloc + ":443")
        return urlunparse(url)
    # OSD cluster
    return urljoin(
        console_url.replace("console-openshift-console", "oauth-openshift"),
        f"/oauth2callback/{auth_name}",
    )


def run(
    integration_name: str,
    ocm_environment: str,
    clusters: Iterable[ClusterV1],
    secret_reader: VaultSecretReader,
    keycloak_vault_paths: Iterable[str],
    vault_input_path: str,
    contacts: Sequence[str],
    dry_run: bool,
) -> None:
    with metrics.transactional_metrics(ocm_environment) as metrics_container:
        # metrics
        expose_base_metrics(
            metrics_container, integration_name, ocm_environment, clusters
        )

        # APIs
        keycloak_instances: list[KeycloakInstance] = []
        for path in keycloak_vault_paths:
            secret = secret_reader.read_all({"path": path})
            iat = secret["initial-access-token"]
            token = jwt.decode(
                iat,
                "secret",
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
            metrics_container.set_gauge(
                RhIdpSSOClientIatExpiration(
                    integration=integration_name,
                    ocm_environment=ocm_environment,
                    path=path,
                ),
                value=token["exp"],
            )
            keycloak_instances.append(
                KeycloakInstance(
                    url=secret["url"],
                    initial_access_token=iat,
                )
            )
        keycloak_map = KeycloakMap(keycloak_instances)

        # run
        try:
            existing_sso_client_ids = fetch_current_state(
                secret_reader=secret_reader, vault_input_path=vault_input_path
            )
            metrics_container.set_gauge(
                RhIdpSSOClientCounter(
                    integration=integration_name,
                    ocm_environment=ocm_environment,
                ),
                value=len(existing_sso_client_ids),
            )
            desired_sso_clients = fetch_desired_state(clusters=clusters)
            act(
                keycloak_map=keycloak_map,
                existing_sso_client_ids=existing_sso_client_ids,
                desired_sso_clients=desired_sso_clients,
                contacts=contacts,
                secret_reader=secret_reader,
                vault_input_path=vault_input_path,
                dry_run=dry_run,
            )
            metrics_container.inc_counter(
                RhIdpSSOClientReconcileCounter(
                    integration=integration_name, ocm_environment=ocm_environment
                )
            )
        except Exception:
            metrics_container.inc_counter(
                RhIdpSSOClientReconcileErrorCounter(
                    integration=integration_name, ocm_environment=ocm_environment
                )
            )
            raise


def fetch_current_state(
    secret_reader: VaultSecretReader, vault_input_path: str
) -> list[str]:
    """Fetch all existing SSO client IDs from vault."""
    return secret_reader.vault_client.list(vault_input_path)  # type: ignore[attr-defined] # mypy doesn't recognize the VaultClient.__new__ method


def fetch_desired_state(
    clusters: Iterable[ClusterV1],
) -> DesiredSSOClients:
    """Compile all desired SSO clients from the given clusters."""
    desired_sso_clients = {}
    for cluster in clusters:
        for auth in cluster.auth:
            if not isinstance(auth, ClusterAuthOIDCV1) or not auth.issuer:
                # this cannot happen, these attributes are set via cluster retrieval method - just make mypy happy
                continue
            cid = cluster_vault_secret_id(
                org_id=cluster.ocm.org_id if cluster.ocm else "unknown",
                cluster_name=cluster.name,
                auth_name=auth.name,
            )
            desired_sso_clients[cid] = (cluster, auth)
    return desired_sso_clients


def act(
    keycloak_map: KeycloakMap,
    secret_reader: VaultSecretReader,
    vault_input_path: str,
    existing_sso_client_ids: list[str],
    desired_sso_clients: DesiredSSOClients,
    contacts: Sequence[str],
    dry_run: bool,
) -> None:
    """Act on the difference between the current and desired state."""
    sso_client_ids_to_remove = set(existing_sso_client_ids) - set(desired_sso_clients)
    sso_client_ids_to_add = set(desired_sso_clients) - set(existing_sso_client_ids)

    for sso_client_id in sso_client_ids_to_remove:
        logging.info(["delete_sso_client", sso_client_id])
        if not dry_run:
            delete_sso_client(
                keycloak_map=keycloak_map,
                sso_client_id=sso_client_id,
                secret_reader=secret_reader,
                vault_input_path=vault_input_path,
            )

    for sso_client_id in sso_client_ids_to_add:
        cluster = desired_sso_clients[sso_client_id][0]
        auth = desired_sso_clients[sso_client_id][1]
        logging.info(["create_sso_client", cluster.name, auth.name, sso_client_id])
        if not dry_run:
            create_sso_client(
                keycloak_map=keycloak_map,
                sso_client_id=sso_client_id,
                cluster=cluster,
                auth=auth,
                contacts=contacts,
                secret_reader=secret_reader,
                vault_input_path=vault_input_path,
            )


def create_sso_client(
    keycloak_map: KeycloakMap,
    sso_client_id: str,
    cluster: ClusterV1,
    auth: ClusterAuthOIDCV1,
    contacts: Sequence[str],
    secret_reader: VaultSecretReader,
    vault_input_path: str,
) -> None:
    """Create an SSO client and store SSO client data in Vault."""
    if not auth.issuer:
        # this cannot happen, these attributes are set via cluster retrieval method - just make mypy happy
        return

    keycloak_api = keycloak_map.get(auth.issuer)

    sso_client = keycloak_api.register_client(
        client_name=sso_client_id,
        redirect_uris=[
            console_url_to_oauth_url(
                console_url=cluster.console_url,
                auth_name=auth.name,
            )
        ],
        initiate_login_uri=cluster.console_url,
        request_uris=[cluster.console_url],
        contacts=contacts,
    )
    secret = cluster_vault_secret(
        vault_input_path=vault_input_path,
        vault_secret_id=sso_client_id,
    )

    secret_reader.vault_client.write(  # type: ignore[attr-defined] # mypy doesn't recognize the VaultClient.__new__ method
        secret={
            "path": secret.path,
            "data": sso_client.dict(),
        },
        decode_base64=False,
    )


def delete_sso_client(
    keycloak_map: KeycloakMap,
    sso_client_id: str,
    secret_reader: VaultSecretReader,
    vault_input_path: str,
) -> None:
    """Delete an SSO client and the stored SSO client data."""
    secret = cluster_vault_secret(
        vault_input_path=vault_input_path,
        vault_secret_id=sso_client_id,
    )
    sso_client = SSOClient(**secret_reader.read_all_secret(secret=secret))
    keycloak_api = keycloak_map.get(sso_client.issuer)
    keycloak_api.delete_client(
        registration_client_uri=sso_client.registration_client_uri,
        registration_access_token=sso_client.registration_access_token,
    )

    secret_reader.vault_client.delete(  # type: ignore[attr-defined] # mypy doesn't recognize the VaultClient.__new__ method
        path=secret.path
    )
