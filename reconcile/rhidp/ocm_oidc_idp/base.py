import logging
import sys
from typing import (
    Iterable,
    Sequence,
)

from reconcile import queries
from reconcile.gql_definitions.rhidp.clusters import (
    ClusterAuthOIDCV1,
    ClusterV1,
)
from reconcile.ocm.types import OCMOidcIdp
from reconcile.rhidp.common import cluster_vault_secret
from reconcile.rhidp.metrics import (
    RhIdpReconcileCounter,
    RhIdpReconcileErrorCounter,
)
from reconcile.utils import metrics
from reconcile.utils.ocm import OCMMap
from reconcile.utils.secret_reader import SecretReaderBase

DEFAULT_EMAIL_CLAIMS: list[str] = ["email"]
DEFAULT_NAME_CLAIMS: list[str] = ["name"]
DEFAULT_USERNAME_CLAIMS: list[str] = ["preferred_username"]
DEFAULT_GROUPS_CLAIMS: list[str] = []


def run(
    integration_name: str,
    clusters: Iterable[ClusterV1],
    secret_reader: SecretReaderBase,
    vault_input_path: str,
    dry_run: bool,
) -> None:
    with metrics.transactional_metrics(integration_name) as metrics_container:
        # APIs
        settings = queries.get_app_interface_settings()
        ocm_map = OCMMap(
            clusters=[cluster.dict(by_alias=True) for cluster in clusters],
            integration=integration_name,
            settings=settings,
        )

        try:
            # run
            current_state = fetch_current_state(ocm_map, clusters)
            desired_state = fetch_desired_state(
                secret_reader, clusters, vault_input_path
            )
            act(dry_run, ocm_map, current_state, desired_state)
            metrics_container.inc_counter(
                RhIdpReconcileCounter(integration=integration_name)
            )
        except Exception:
            metrics_container.inc_counter(
                RhIdpReconcileErrorCounter(integration=integration_name)
            )
            raise


def fetch_current_state(
    ocm_map: OCMMap, clusters: Iterable[ClusterV1]
) -> list[OCMOidcIdp]:
    """Fetch all current configured OIDC identity providers."""
    current_state = []

    for cluster in clusters:
        ocm = ocm_map.get(cluster.name)
        current_state += ocm.get_oidc_idps(cluster.name)

    return current_state


def fetch_desired_state(
    secret_reader: SecretReaderBase,
    clusters: Iterable[ClusterV1],
    vault_input_path: str,
) -> list[OCMOidcIdp]:
    """Compile a list of desired OIDC identity providers from app-interface."""
    desired_state = []
    for cluster in clusters:
        for auth in cluster.auth:
            if (
                not isinstance(auth, ClusterAuthOIDCV1)
                or not auth.issuer
                or not cluster.ocm
            ):
                # this cannot happen, this attribute is set via cluster retrieval method - just make mypy happy
                continue

            secret = cluster_vault_secret(
                org_id=cluster.ocm.org_id,
                cluster_name=cluster.name,
                auth_name=auth.name,
                vault_input_path=vault_input_path,
            )
            try:
                oauth_data = secret_reader.read_all(secret)
            except Exception:
                logging.warning(
                    f"Unable to read secret in path {secret['path']}. "
                    f"Maybe not created yet? Skipping OIDC config for cluster {cluster.name}"
                )
                continue

            client_id = oauth_data["client_id"]
            client_secret = oauth_data["client_secret"]
            ec = (
                auth.claims.email
                if auth.claims and auth.claims.email
                else DEFAULT_EMAIL_CLAIMS
            )
            nc = (
                auth.claims.name
                if auth.claims and auth.claims.name
                else DEFAULT_NAME_CLAIMS
            )
            uc = (
                auth.claims.username
                if auth.claims and auth.claims.username
                else DEFAULT_USERNAME_CLAIMS
            )
            gc = (
                auth.claims.groups
                if auth.claims and auth.claims.groups
                else DEFAULT_GROUPS_CLAIMS
            )
            desired_state.append(
                OCMOidcIdp(
                    cluster=cluster.name,
                    name=auth.name,
                    client_id=client_id,
                    client_secret=client_secret,
                    issuer=auth.issuer,
                    email_claims=ec,
                    name_claims=nc,
                    username_claims=uc,
                    groups_claims=gc,
                )
            )

    return desired_state


def act(
    dry_run: bool,
    ocm_map: OCMMap,
    current_state: Sequence[OCMOidcIdp],
    desired_state: Sequence[OCMOidcIdp],
) -> None:
    """Compare current and desired OIDC identity providers and add, remove, or update them."""
    to_add = set(desired_state) - set(current_state)
    to_remove = set(current_state) - set(desired_state)
    to_compare = set(current_state) & set(desired_state)

    for idp in to_remove:
        logging.info(["remove_oidc_idp", idp.cluster, idp.name])
        if not idp.id:
            logging.error(
                "No identity provider id was given. This should never ever happen!"
            )
            sys.exit(1)
        if not dry_run:
            ocm = ocm_map.get(idp.cluster)
            ocm.delete_idp(idp.cluster, idp.id)

    for idp in to_add:
        logging.info(["create_oidc_idp", idp.cluster, idp.name])
        if not dry_run:
            ocm = ocm_map.get(idp.cluster)
            ocm.create_oidc_idp(idp)

    for idp in to_compare:
        current_idp = current_state[current_state.index(idp)]
        desired_idp = desired_state[desired_state.index(idp)]
        if not current_idp.differ(desired_idp):
            # no changes detected
            continue

        logging.info(["update_oidc_idp", desired_idp.cluster, desired_idp.name])
        if not current_idp.id:
            logging.error(
                "No identity provider id was given. This should never ever happen!"
            )
            sys.exit(1)
        if not dry_run:
            ocm = ocm_map.get(desired_idp.cluster)
            ocm.update_oidc_idp(current_idp.id, desired_idp)
