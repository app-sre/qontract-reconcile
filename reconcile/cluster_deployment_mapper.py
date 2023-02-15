import logging
import sys
from typing import (
    Any,
    Optional,
)

from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils.oc import OCLogMsg
from reconcile.utils.oc_map import init_oc_map_from_clusters
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.vault import VaultClient

QONTRACT_INTEGRATION = "cluster-deployment-mapper"


def run(dry_run: bool, vault_output_path: Optional[str]) -> None:
    """Get Hive ClusterDeployments from clusters and save mapping to Vault"""
    if not vault_output_path:
        logging.error("must supply vault output path")
        sys.exit(ExitCodes.ERROR)

    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    clusters = get_clusters()
    oc_map = init_oc_map_from_clusters(
        clusters=clusters,
        secret_reader=secret_reader,
        integration=QONTRACT_INTEGRATION,
        thread_pool_size=1,
        init_api_resources=True,
    )
    results: list[dict[str, Any]] = []
    for c in clusters:
        name = c.name
        oc = oc_map.get(name)
        if not oc or isinstance(oc, OCLogMsg):
            continue
        if "ClusterDeployment" not in (oc.api_resources or []):
            continue
        logging.info(f"[{name}] getting ClusterDeployments")
        cds = oc.get_all("ClusterDeployment", all_namespaces=True)["items"]
        for cd in cds:
            try:
                item = {
                    "id": cd["spec"]["clusterMetadata"]["clusterID"],
                    "cluster": name,
                }
                results.append(item)
            except KeyError:
                pass

    if not dry_run:
        logging.info("writing ClusterDeployments to vault")
        vault_client = VaultClient()
        secret = {
            "path": f"{vault_output_path}/{QONTRACT_INTEGRATION}",
            "data": {
                "map": "\n".join(f"{item['id']}: {item['cluster']}" for item in results)
            },
        }
        # mypy doesn't like our fancy way of creating a VaultClient
        vault_client.write(secret, decode_base64=False)  # type: ignore[attr-defined]
