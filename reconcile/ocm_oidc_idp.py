import logging
import sys
from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from typing import Any

from reconcile import queries
from reconcile.gql_definitions.ocm_oidc_idp.clusters import (
    ClusterAuthOIDCV1,
    ClusterV1,
)
from reconcile.gql_definitions.ocm_oidc_idp.clusters import query as cluster_query
from reconcile.ocm.types import OCMOidcIdp
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import OCMMap
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "ocm-oidc-idp"

DEFAULT_EMAIL_CLAIMS: list[str] = ["email"]
DEFAULT_NAME_CLAIMS: list[str] = ["name"]
DEFAULT_USERNAME_CLAIMS: list[str] = ["preferred_username"]
DEFAULT_GROUPS_CLAIMS: list[str] = []


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
    secret_reader: SecretReader,
    clusters: Iterable[ClusterV1],
    vault_input_path: str,
) -> list[OCMOidcIdp]:
    """Compile a list of desired OIDC identity providers from app-interface."""
    desired_state = []
    error = False
    for cluster in clusters:
        for auth in cluster.auth:
            if not isinstance(auth, ClusterAuthOIDCV1):
                continue

            if not auth.issuer:
                logging.error(
                    f"{cluster.name} auth={auth.name} doesn't have an issuer url set."
                )
                sys.exit(1)

            secret = {
                "path": f"{vault_input_path.rstrip('/')}/{QONTRACT_INTEGRATION}/{auth.name}/{cluster.name}"
            }
            try:
                oauth_data = secret_reader.read_all(secret)
                client_id = oauth_data["client_id"]
                client_secret = oauth_data["client_secret"]
            except Exception:
                logging.error(f"unable to read secret in path {secret['path']}")
                error = True
                continue
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

    if error:
        sys.exit(1)

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
    for idp in to_add:
        logging.info(["create_oidc_idp", idp.cluster, idp.name])
        if not dry_run:
            ocm = ocm_map.get(idp.cluster)
            ocm.create_oidc_idp(idp)

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


def get_clusters(query_func: Callable) -> list[ClusterV1]:
    """Get all clusters with an OCM relation from app-interface."""
    data = cluster_query(query_func, variables={})
    return [
        c
        for c in data.clusters or []
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and c.ocm is not None
    ]


def run(dry_run: bool, vault_input_path: str) -> None:
    if not vault_input_path:
        logging.error("must supply vault input path")
        sys.exit(1)
    gqlapi = gql.get_api()
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    # data query
    clusters = get_clusters(gqlapi.query)
    if not clusters:
        logging.debug("No oidc-idp definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    # APIs
    ocm_map = OCMMap(
        clusters=[cluster.dict(by_alias=True) for cluster in clusters],
        integration=QONTRACT_INTEGRATION,
        settings=settings,
    )

    # run
    current_state = fetch_current_state(ocm_map, clusters)
    desired_state = fetch_desired_state(secret_reader, clusters, vault_input_path)
    act(dry_run, ocm_map, current_state, desired_state)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {"clusters": [c.dict() for c in get_clusters(gqlapi.query)]}
