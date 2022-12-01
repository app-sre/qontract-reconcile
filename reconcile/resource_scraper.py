import logging
import sys
from typing import cast

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.oc import OC_Map
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "resource-scraper"


def run(dry_run, namespace_name, resource_kind, vault_output_path):
    """Get resources from clusters and store in Vault."""
    if not namespace_name:
        logging.error("must supply namespace name")
        sys.exit(ExitCodes.ERROR)
    if not resource_kind:
        logging.error("must supply resource kind")
        sys.exit(ExitCodes.ERROR)
    if not vault_output_path:
        logging.error("must supply vault output path")
        sys.exit(ExitCodes.ERROR)

    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters(minimal=True)
    oc_map = OC_Map(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        thread_pool_size=10,
        settings=settings,
        init_api_resources=True,
    )
    results = []
    for c in clusters:
        cluster_name = c["name"]
        oc = oc_map.get(cluster_name)
        if not oc:
            continue
        resources = oc.get(namespace_name, resource_kind)["items"]
        for r in resources:
            item = {
                "cluster": cluster_name,
                "name": r["metadata"]["name"],
                "data": r["data"],
            }
            results.append(item)

    if not dry_run:
        vault_client = cast(_VaultClient, VaultClient())
        for item in results:
            secret = {
                "path": f"{vault_output_path}/{QONTRACT_INTEGRATION}/{item['cluster']}/{namespace_name}/{item['name']}",
                "data": item["data"],
            }
            vault_client.write(secret, decode_base64=False)
