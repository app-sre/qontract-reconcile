import base64
import json
import logging
import subprocess
import sys
import tempfile
import urllib.request
from typing import cast
from urllib.error import URLError

from pydantic import BaseModel
from sretoolbox.utils import retry

import reconcile.gql_definitions.openshift_cluster_bots.clusters as clusters_gql
from reconcile import mr_client_gateway, queries
from reconcile.gql_definitions.openshift_cluster_bots.clusters import ClusterV1
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.mr import clusters_updates
from reconcile.utils.ocm import OCM, OCMMap
from reconcile.utils.openshift_resource import (
    QONTRACT_ANNOTATION_INTEGRATION,
    QONTRACT_ANNOTATION_INTEGRATION_VERSION,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import VaultClient, _VaultClient

QONTRACT_INTEGRATION = "openshift-cluster-bots"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class Config(BaseModel):
    gitlab_project_id: str
    vault_creds_path: str
    dedicated_admin_ns: str
    dedicated_admin_sa: str
    cluster_admin_ns: str
    cluster_admin_sa: str
    dry_run: bool


def cluster_misses_bot_tokens(cluster: ClusterV1) -> bool:
    return cluster.automation_token is None or (
        cluster.cluster_admin is True and cluster.cluster_admin_automation_token is None
    )


def cluster_is_reachable(cluster: ClusterV1) -> bool:
    if not cluster.server_url:
        return False
    # https://kubernetes.io/docs/reference/using-api/health-checks/
    url = f"{cluster.server_url}/readyz"
    try:
        res = urllib.request.urlopen(url, timeout=10)
        return res is not None and res.getcode() == 200
    except URLError as e:
        logging.debug(f"[{cluster.name}] API URL unreachable: {e.reason}")
        return False


def vault_secret(
    cluster: ClusterV1, config: Config, cluster_admin: bool = False
) -> dict[str, str]:
    secret_key = f"{config.vault_creds_path}/{cluster.name}"
    if cluster_admin:
        secret_key = f"{secret_key}-cluster-admin"
    return {
        "path": secret_key,
        "field": "token",
    }


def vault_data(
    cluster: ClusterV1, config: Config, token: str, cluster_admin: bool
) -> dict[str, str]:
    username = f"{config.dedicated_admin_ns}/{config.dedicated_admin_sa} # not used by automation"
    if cluster_admin:
        username = f"{config.cluster_admin_ns}/{config.cluster_admin_sa} # not used by automation"
    return {
        "server": cluster.server_url,
        "token": token,
        "username": username,
    }


# We're not using the generic OC classes here because we use a kubeconfig instead of a token
# Since that is very exceptional and should be done only in this context, it is preferable to
# not update the generic client implementations.
def oc(
    kubeconfig: str, namespace: str, command: list[str], stdin: bytes | None = None
) -> dict | None:
    ret = subprocess.run(
        ["oc", "--kubeconfig", kubeconfig, "-n", namespace, "-o", "json", *command],
        input=stdin,
        check=True,
        capture_output=True,
    )
    if not ret.stdout:
        return None
    return json.loads(ret.stdout.decode())


def oc_apply(kubeconfig: str, namespace: str, items: list[dict]) -> None:
    for item in items:
        stdin = json.dumps(item).encode()
        oc(kubeconfig, namespace, ["apply", "-f", "-"], stdin)


def sa_secret_name(sa: str) -> str:
    return f"{sa}-token"


class TokenNotReadyException(Exception):
    pass


# retry allows to let the kube API the time to generate the token and fill the secret
@retry()
def retrieve_token(kubeconfig: str, namespace: str, sa: str) -> str:
    secret = oc(kubeconfig, namespace, ["get", "secret", sa_secret_name(sa)])
    if not secret or "token" not in secret.get("data", {}):
        raise TokenNotReadyException()
    b64_token = secret["data"]["token"]
    return base64.b64decode(b64_token).decode()


def create_sa(
    kubeconfig: str,
    namespace: str,
    sa: str,
    create_namespace: bool = False,
    cluster_admin: bool = False,
) -> str:
    items: list[dict] = []
    if create_namespace:
        items.append({
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": namespace},
        })
    items.extend([
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "annotations": {
                    QONTRACT_ANNOTATION_INTEGRATION: QONTRACT_INTEGRATION,
                    QONTRACT_ANNOTATION_INTEGRATION_VERSION: QONTRACT_INTEGRATION_VERSION,
                },
                "name": sa,
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "annotations": {
                    "kubernetes.io/service-account.name": sa,
                    QONTRACT_ANNOTATION_INTEGRATION: QONTRACT_INTEGRATION,
                    QONTRACT_ANNOTATION_INTEGRATION_VERSION: QONTRACT_INTEGRATION_VERSION,
                },
                "name": sa_secret_name(sa),
            },
            "type": "kubernetes.io/service-account-token",
        },
    ])
    if cluster_admin:
        items.append({
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {
                "name": f"{namespace}-{sa}",
            },
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": "cluster-admin",
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": sa,
                    "namespace": namespace,
                }
            ],
        })

    oc_apply(kubeconfig, namespace, items)
    token = retrieve_token(kubeconfig, namespace, sa)
    return token


def create_cluster_bots(
    cluster: ClusterV1, ocm: OCM, config: Config
) -> tuple[str | None, str | None]:
    kubeconfig_content = ocm.get_kubeconfig(cluster.name)
    if not kubeconfig_content:
        logging.error(
            f"[{cluster.name}] Could not get cluster credentials from OCM (kubeconfig)"
        )
        return None, None

    token = None
    admin_token = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="locale", delete=True
        ) as kc:
            kc.write(kubeconfig_content)
            kc.flush()
            logging.info(
                f"[{cluster.name}] create {config.dedicated_admin_sa} service account"
            )
            if not config.dry_run:
                token = create_sa(
                    kc.name, config.dedicated_admin_ns, config.dedicated_admin_sa
                )
            if cluster.cluster_admin:
                logging.info(
                    f"[{cluster.name}] create {config.cluster_admin_sa} service account"
                )
                if not config.dry_run:
                    admin_token = create_sa(
                        kc.name,
                        config.cluster_admin_ns,
                        config.cluster_admin_sa,
                        create_namespace=True,
                        cluster_admin=True,
                    )
    except subprocess.CalledProcessError as e:
        logging.error(e.stderr)
        raise e

    return token, admin_token


def update_vault(
    cluster: ClusterV1, config: Config, token: str, admin_token: str | None
) -> None:
    vault = cast(_VaultClient, VaultClient())
    vault.write(
        {
            "path": vault_secret(cluster, config, cluster_admin=False)["path"],
            "data": vault_data(cluster, config, token, cluster_admin=False),
        },
        decode_base64=False,
    )
    if cluster.cluster_admin and admin_token:
        vault.write(
            {
                "path": vault_secret(cluster, config, cluster_admin=True)["path"],
                "data": vault_data(cluster, config, admin_token, cluster_admin=True),
            },
            decode_base64=False,
        )


def submit_mr(clusters: list[ClusterV1], config: Config) -> None:
    cluster_updates: dict[str, dict] = {}
    for cluster in clusters:
        root = {"automationToken": vault_secret(cluster, config, cluster_admin=False)}
        if cluster.cluster_admin:
            root["clusterAdminAutomationToken"] = vault_secret(
                cluster, config, cluster_admin=True
            )
        cluster_updates[cluster.name] = {
            "path": "data" + cluster.path,
            "root": root,
            "spec": {},
        }
    mr = clusters_updates.CreateClustersUpdates(cluster_updates)
    with mr_client_gateway.init(gitlab_project_id=config.gitlab_project_id) as mr_cli:
        mr.submit(cli=mr_cli)


def create_all_bots(
    clusters: list[ClusterV1],
    ocm_map: OCMMap,
    config: Config,
) -> None:
    for cluster in clusters:
        ocm = ocm_map.get(cluster.name)
        token, admin_token = create_cluster_bots(cluster, ocm, config)
        if token and not config.dry_run:
            update_vault(cluster, config, token, admin_token)
    if not config.dry_run:
        submit_mr(clusters, config)


def filter_clusters(clusters: list[ClusterV1]) -> list[ClusterV1]:
    return [
        cluster
        for cluster in clusters
        if integration_is_enabled(QONTRACT_INTEGRATION, cluster)
        and cluster.ocm is not None
        and cluster_misses_bot_tokens(cluster)
        and cluster_is_reachable(cluster)
    ]


def get_ocm_map(clusters: list[ClusterV1]) -> OCMMap:
    settings = queries.get_app_interface_settings()
    clusters_info = [c.dict(by_alias=True) for c in clusters]
    return OCMMap(
        settings=settings,
        clusters=clusters_info,
        integration=QONTRACT_INTEGRATION,
    )


def run(
    dry_run: bool,
    gitlab_project_id: str,
    vault_creds_path: str,
    dedicated_admin_ns: str,
    dedicated_admin_sa: str,
    cluster_admin_ns: str,
    cluster_admin_sa: str,
) -> None:
    config = Config(
        gitlab_project_id=gitlab_project_id,
        vault_creds_path=vault_creds_path,
        dedicated_admin_ns=dedicated_admin_ns,
        dedicated_admin_sa=dedicated_admin_sa,
        cluster_admin_ns=cluster_admin_ns,
        cluster_admin_sa=cluster_admin_sa,
        dry_run=dry_run,
    )

    query_func = gql.get_api().query
    clusters = clusters_gql.query(query_func=query_func).clusters
    if not clusters:
        logging.debug("No cluster definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    clusters = filter_clusters(clusters)
    if not clusters:
        logging.debug("Nothing to do")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map = get_ocm_map(clusters)

    create_all_bots(clusters, ocm_map, config)
