import sys
import logging
from typing import Any
from collections.abc import Mapping

from reconcile import queries

from reconcile.utils.ocm import OCMMap
from reconcile.utils.secret_reader import SecretReader
from reconcile.status import ExitCodes
from reconcile.ocm.utils import cluster_disabled_integrations

QONTRACT_INTEGRATION = "ocm-github-idp"


def fetch_current_state(clusters, settings):
    current_state = []
    ocm_map = OCMMap(
        clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )

    for cluster_info in clusters:
        cluster = cluster_info["name"]
        ocm = ocm_map.get(cluster)
        idps = ocm.get_github_idp_teams(cluster)
        current_state.extend(idps)

    return ocm_map, current_state


def fetch_desired_state(clusters, vault_input_path, settings):
    desired_state = []
    error = False
    secret_reader = SecretReader(settings=settings)
    for cluster_info in clusters:
        cluster = cluster_info["name"]
        for auth in cluster_info["auth"]:
            if auth["service"] != "github-org-team":
                continue

            org = auth["org"]
            team = auth["team"]
            secret = {
                "path": f"{vault_input_path}/{QONTRACT_INTEGRATION}/{auth['service']}/{org}/{team}"
            }
            try:
                oauth_data = secret_reader.read_all(secret)
                client_id = oauth_data["client-id"]
                client_secret = oauth_data["client-secret"]
            except Exception:
                logging.error(f"unable to read secret in path {secret['path']}")
                error = True
                continue
            item = {
                "cluster": cluster,
                "name": f"github-{org}",
                "client_id": client_id,
                "client_secret": client_secret,
                "teams": [f"{org}/{team}"],
            }
            desired_state.append(item)

    return desired_state, error


def sanitize(state):
    return {k: v for k, v in state.items() if k != "client_secret"}


def act(dry_run, ocm_map, current_state, desired_state):
    to_add = [d for d in desired_state if sanitize(d) not in current_state]
    for item in to_add:
        cluster = item["cluster"]
        idp_name = item["name"]
        team = item["teams"][0]
        logging.info(["create_github_idp", cluster, idp_name, team])

        if not dry_run:
            ocm = ocm_map.get(cluster)
            ocm.create_github_idp_teams(item)


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return cluster.get("ocm") is not None and cluster.get("auth") is not None


def run(dry_run, vault_input_path=""):
    if not vault_input_path:
        logging.error("must supply vault input path")
        sys.exit(1)
    settings = queries.get_app_interface_settings()
    clusters = [
        c
        for c in queries.get_clusters()
        if QONTRACT_INTEGRATION not in cluster_disabled_integrations(c)
        and _cluster_is_compatible(c)
    ]
    if not clusters:
        logging.debug("No github-idp definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state = fetch_current_state(clusters, settings)
    desired_state, error = fetch_desired_state(clusters, vault_input_path, settings)
    if error:
        sys.exit(1)
    act(dry_run, ocm_map, current_state, desired_state)
