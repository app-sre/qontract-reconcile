import sys
import logging

from reconcile import queries

from reconcile.status import ExitCodes
from reconcile.utils.oc import OC_Map
from reconcile.utils.vault import VaultClient


QONTRACT_INTEGRATION = "cluster-deployment-mapper"


def run(dry_run, vault_output_path):
    """Get Hive ClusterDeployments from clusters and save mapping to Vault"""
    if not vault_output_path:
        logging.error("must supply vault output path")
        sys.exit(ExitCodes.ERROR)

    clusters = queries.get_clusters()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        thread_pool_size=1,
        settings=settings,
        init_api_resources=True,
    )
    results = []
    for c in clusters:
        name = c["name"]
        oc = oc_map.get(name)
        if not oc:
            continue
        if "ClusterDeployment" not in oc.api_resources:
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
        vault_client.write(secret, decode_base64=False)
