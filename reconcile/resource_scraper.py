import logging
import sys
from typing import (
    cast,
)

from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.utils.oc import OCLogMsg
from reconcile.utils.oc_map import init_oc_map_from_clusters
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "resource-scraper"


def run(
    dry_run: bool,
    namespace_name: str | None,
    resource_kind: str | None,
    vault_output_path: str | None,
) -> None:
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

    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    clusters = get_clusters_minimal()
    oc_map = init_oc_map_from_clusters(
        clusters=clusters,
        secret_reader=secret_reader,
        integration=QONTRACT_INTEGRATION,
        thread_pool_size=10,
        init_api_resources=True,
    )
    results = []
    for c in clusters:
        cluster_name = c.name
        oc = oc_map.get(cluster_name)
        if not oc or isinstance(oc, OCLogMsg):
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
