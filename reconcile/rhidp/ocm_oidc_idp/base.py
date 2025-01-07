import logging
import operator
from collections.abc import (
    Iterable,
    Sequence,
)

from pydantic import BaseModel

from reconcile.rhidp.common import (
    Cluster,
    cluster_vault_secret,
    expose_base_metrics,
)
from reconcile.rhidp.ocm_oidc_idp.metrics import (
    RhIdpOCMOidcIdpReconcileCounter,
    RhIdpOCMOidcIdpReconcileErrorCounter,
)
from reconcile.utils import metrics
from reconcile.utils.differ import diff_iterables
from reconcile.utils.keycloak import SSOClient
from reconcile.utils.ocm.base import (
    OCMOIdentityProvider,
    OCMOIdentityProviderGithub,
    OCMOIdentityProviderOidc,
    OCMOIdentityProviderOidcOpenId,
)
from reconcile.utils.ocm.identity_providers import (
    add_identity_provider,
    delete_identity_provider,
    get_identity_providers,
    update_identity_provider,
)
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import SecretReaderBase


class IDPState(BaseModel):
    cluster: Cluster
    idp: OCMOIdentityProvider | OCMOIdentityProviderOidc | OCMOIdentityProviderGithub

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, IDPState):
            raise NotImplementedError("Cannot compare to non IDPState objects.")
        return self.idp == value.idp


def run(
    integration_name: str,
    ocm_environment: str,
    clusters: Iterable[Cluster],
    secret_reader: SecretReaderBase,
    ocm_api: OCMBaseClient,
    vault_input_path: str,
    dry_run: bool,
    managed_idps: list[str] | None = None,
) -> None:
    with metrics.transactional_metrics(ocm_environment) as metrics_container:
        # metrics
        expose_base_metrics(
            metrics_container, integration_name, ocm_environment, clusters
        )

        try:
            # run
            current_state = fetch_current_state(ocm_api, clusters)
            desired_state = fetch_desired_state(
                secret_reader, clusters, vault_input_path
            )
            act(
                dry_run,
                ocm_api,
                current_state,
                desired_state,
                managed_idps=managed_idps or [],
            )
            metrics_container.inc_counter(
                RhIdpOCMOidcIdpReconcileCounter(
                    integration=integration_name, ocm_environment=ocm_environment
                )
            )
        except Exception:
            metrics_container.inc_counter(
                RhIdpOCMOidcIdpReconcileErrorCounter(
                    integration=integration_name, ocm_environment=ocm_environment
                )
            )
            raise


def fetch_current_state(
    ocm_api: OCMBaseClient, clusters: Iterable[Cluster]
) -> list[IDPState]:
    """Fetch all current configured OIDC identity providers."""
    return [
        IDPState(cluster=cluster, idp=idp)
        for cluster in clusters
        for idp in get_identity_providers(
            ocm_api=ocm_api, ocm_cluster=cluster.ocm_cluster
        )
    ]


def fetch_desired_state(
    secret_reader: SecretReaderBase,
    clusters: Iterable[Cluster],
    vault_input_path: str,
) -> list[IDPState]:
    """Compile a list of desired OIDC identity providers from app-interface."""
    desired_state: list[IDPState] = []
    for cluster in clusters:
        if not cluster.auth.oidc_enabled:
            continue

        secret = cluster_vault_secret(
            org_id=cluster.organization_id,
            cluster_name=cluster.name,
            auth_name=cluster.auth.name,
            issuer_url=cluster.auth.issuer,
            vault_input_path=vault_input_path,
        )
        try:
            oauth_data = secret_reader.read_all_secret(secret)
        except Exception:
            logging.warning(
                f"Unable to read secret in path {secret.path}. "
                f"Maybe not created yet? Skipping OIDC config for cluster {cluster.name}"
            )
            continue

        sso_client = SSOClient(**oauth_data)
        if sso_client.issuer != cluster.auth.issuer:
            # this can only happen if someone manually change the secret or copied it
            logging.error(
                f"SSO client issuer {sso_client.issuer} does not match configured cluster issuer "
                f"{cluster.auth.issuer}. Skipping OIDC config for cluster {cluster.name}"
            )
            continue
        desired_state.append(
            IDPState(
                cluster=cluster,
                idp=OCMOIdentityProviderOidc(
                    name=cluster.auth.name,
                    open_id=OCMOIdentityProviderOidcOpenId(
                        client_id=sso_client.client_id,
                        client_secret=sso_client.client_secret,
                        issuer=cluster.auth.issuer,
                    ),
                ),
            )
        )

    return desired_state


def act(
    dry_run: bool,
    ocm_api: OCMBaseClient,
    current_state: Sequence[IDPState],
    desired_state: Sequence[IDPState],
    managed_idps: list[str],
) -> None:
    """Compare current and desired OIDC identity providers and add, remove, or update them."""
    diff_result = diff_iterables(
        current_state,
        desired_state,
        key=lambda idp_state: ((
            idp_state.cluster.organization_id,
            idp_state.cluster.name,
            idp_state.idp.type,
            idp_state.idp.name,
        )),
        equal=operator.eq,
    )

    for idp_state in diff_result.delete.values():
        if (
            managed_idps
            and idp_state.idp.name not in managed_idps
            and not idp_state.cluster.auth.enforced
        ):
            logging.debug(f"Skipping removal of unmanged '{idp_state.idp.name}' IDP.")
            continue
        logging.info(["remove_oidc_idp", idp_state.cluster.name, idp_state.idp.name])
        if not dry_run:
            delete_identity_provider(ocm_api, idp_state.idp)

    for idp_state in diff_result.add.values():
        if not isinstance(idp_state.idp, OCMOIdentityProviderOidc):
            logging.error(
                f"Identity provider {idp_state.idp.name} is not an OIDC identity provider."
            )
            continue
        logging.info(["create_oidc_idp", idp_state.cluster.name, idp_state.idp.name])
        if not dry_run:
            add_identity_provider(ocm_api, idp_state.cluster.ocm_cluster, idp_state.idp)

    for diff_pair in diff_result.change.values():
        current_idp_state = diff_pair.current
        desired_idp_state = diff_pair.desired
        current_idp = current_idp_state.idp
        desired_idp = desired_idp_state.idp
        desired_idp.href = current_idp.href

        if not isinstance(desired_idp, OCMOIdentityProviderOidc):
            logging.error(
                f"Identity provider {desired_idp.name} is not an OIDC identity provider."
            )
            continue
        logging.info([
            "update_oidc_idp",
            desired_idp_state.cluster.name,
            desired_idp.name,
        ])
        if not dry_run:
            update_identity_provider(ocm_api, desired_idp)
