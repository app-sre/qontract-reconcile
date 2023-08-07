from typing import (
    Any,
    Optional,
)

from reconcile.utils.ocm.base import OCMAddonInstallation
from reconcile.utils.ocm_base_client import OCMBaseClient


def get_addons_for_cluster(
    ocm_api: OCMBaseClient,
    cluster_id: str,
    addon_latest_versions: dict[str, str],
    required_state: Optional[str],
) -> list[OCMAddonInstallation]:
    """
    Returns a list of Addons installed on a cluster

    :param cluster_id: ID of the cluster
    :param addon_latest_versions: dict of addon_id -> latest version. This allows us to
        populate the addonsinstalation available upgrades in an efficient way.
    :param required_state: only return addons with this state
    """

    params: Optional[dict[str, Any]] = None
    if required_state:
        params = {"search": f"state='{required_state}'"}

    addons = []
    for addon in ocm_api.get_paginated(
        api_path=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/addons",
        params=params,
    ):
        current_version = addon["addon_version"]["id"]
        latest_version = addon_latest_versions.get(addon["id"])
        addon["addon_version"]["available_upgrades"] = (
            [latest_version] if latest_version != current_version else []
        )
        addons.append(OCMAddonInstallation(**addon))
    return addons


def get_addon_latest_versions(ocm_api: OCMBaseClient) -> dict[str, str]:
    """
    Returns the latest version for each addon.
    """
    latest_versions: dict[str, str] = {}
    for addon in ocm_api.get_paginated("/api/clusters_mgmt/v1/addons"):
        addon_id = addon["id"]
        latest_versions[addon_id] = addon["version"]["id"]
    return latest_versions
