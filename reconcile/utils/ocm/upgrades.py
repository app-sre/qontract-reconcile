from typing import (
    Any,
    Optional,
    Union,
)

from reconcile.utils.ocm.base import OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient

UPGRADE_POLICY_DESIRED_KEYS = {"id", "schedule_type", "schedule", "next_run", "version"}
ADDON_UPGRADE_POLICY_DESIRED_KEYS = {
    "id",
    "addon_id",
    "schedule_type",
    "schedule",
    "next_run",
    "version",
}


def build_cluster_url(cluster_id: str) -> str:
    return f"/api/clusters_mgmt/v1/clusters/{cluster_id}"


#
# ADDON UPGRADE POLICIES
#


def get_addon_upgrade_policies(
    ocm_api: OCMBaseClient, cluster_id: str, addon_id: Optional[str] = None
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for policy in ocm_api.get_paginated(
        f"{build_cluster_url(cluster_id)}/addon_upgrade_policies"
    ):
        if addon_id and policy["addon_id"] != addon_id:
            continue
        policy_data = {
            k: v for k, v in policy.items() if k in ADDON_UPGRADE_POLICY_DESIRED_KEYS
        }
        policy_data["state"] = get_addon_upgrade_policy_state(
            ocm_api, cluster_id, policy["id"]
        )
        results.append(policy_data)

    return results


def get_addon_upgrade_policy_state(
    ocm_api: OCMBaseClient, cluster_id: str, addon_upgrade_policy_id: str
) -> Optional[str]:
    try:
        state_data = ocm_api.get(
            f"{build_cluster_url(cluster_id)}/addon_upgrade_policies/{addon_upgrade_policy_id}/state"
        )
        return state_data.get("value")
    except Exception:
        return None


def create_addon_upgrade_policy(
    ocm_api: OCMBaseClient, cluster_id: str, spec: dict
) -> None:
    """
    Creates a new Addon Upgrade Policy
    """
    ocm_api.post(f"{build_cluster_url(cluster_id)}/addon_upgrade_policies", spec)


def delete_addon_upgrade_policy(
    ocm_api: OCMBaseClient, cluster_id: str, policy_id: str
) -> None:
    """
    Deletes an existing Addon Upgrade Policy
    """
    ocm_api.delete(
        f"{build_cluster_url(cluster_id)}/addon_upgrade_policies/{policy_id}"
    )


#
# UPGRADE POLICIES
#


def get_upgrade_policies(
    ocm_api: OCMBaseClient, cluster_id: str, schedule_type: Optional[str] = None
) -> list[dict[str, Any]]:
    """Returns a list of details of Upgrade Policies

    :param cluster: cluster name

    :type cluster: string
    """
    results: list[dict[str, Any]] = []

    for policy in ocm_api.get_paginated(
        f"{build_cluster_url(cluster_id)}/upgrade_policies"
    ):
        if schedule_type and policy["schedule_type"] != schedule_type:
            continue
        policy_data = {
            k: v for k, v in policy.items() if k in UPGRADE_POLICY_DESIRED_KEYS
        }
        policy_data["state"] = get_upgrade_policy_state(
            ocm_api, cluster_id, policy["id"]
        )
        results.append(policy_data)

    return results


def get_upgrade_policy_state(
    ocm_api: OCMBaseClient, cluster_id: str, upgrade_policy_id: str
) -> Optional[str]:
    try:
        state_data = ocm_api.get(
            f"{build_cluster_url(cluster_id)}/upgrade_policies/{upgrade_policy_id}/state"
        )
        return state_data.get("value")
    except Exception:
        return None


def create_upgrade_policy(ocm_api: OCMBaseClient, cluster_id: str, spec: dict) -> None:
    """
    Creates a new Upgrade Policy
    """
    ocm_api.post(f"{build_cluster_url(cluster_id)}/upgrade_policies", spec)


def delete_upgrade_policy(
    ocm_api: OCMBaseClient, cluster_id: str, policy_id: str
) -> None:
    """
    Deletes an existing Upgrade Policy
    """
    ocm_api.delete(f"{build_cluster_url(cluster_id)}/upgrade_policies/{policy_id}")


#
# CONTROL PLANE UPGRADE POLICIES
#


def get_control_plane_upgrade_policies(
    ocm_api: OCMBaseClient, cluster_id: str, schedule_type: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Returns a list of details of Upgrade Policies
    """
    results: list[dict[str, Any]] = []
    for policy in ocm_api.get_paginated(
        f"{build_cluster_url(cluster_id)}/control_plane/upgrade_policies"
    ):
        if schedule_type and policy["schedule_type"] != schedule_type:
            continue
        policy_data = {
            k: v for k, v in policy.items() if k in UPGRADE_POLICY_DESIRED_KEYS
        }
        policy_data["state"] = policy.get("state", {}).get("value")
        results.append(policy_data)
    return results


def create_control_plane_upgrade_policy(
    ocm_api: OCMBaseClient, cluster_id: str, spec: dict
) -> None:
    """
    Creates a new Upgrade Policy for the control plane
    """
    ocm_api.post(
        f"{build_cluster_url(cluster_id)}/control_plane/upgrade_policies", spec
    )


def delete_control_plane_upgrade_policy(
    ocm_api: OCMBaseClient, cluster_id: str, upgrade_policy_id: str
) -> None:
    """
    Deletes an existing Control Plane Upgrade Policy
    """
    ocm_api.delete(
        f"{build_cluster_url(cluster_id)}/control_plane/upgrade_policies/{upgrade_policy_id}"
    )


#
# NODE POOLUPGRADE POLICIES
#


def get_node_pool_upgrade_policies(
    ocm_api: OCMBaseClient, cluster_id: str, node_pool: str
) -> list[dict[str, Any]]:
    """
    Returns a list of details of Upgrade Policies
    """
    results: list[dict[str, Any]] = []
    for policy in ocm_api.get_paginated(
        f"{build_cluster_url(cluster_id)}/node_pools/{node_pool}/upgrade_policies"
    ):
        results.append(
            {k: v for k, v in policy.items() if k in UPGRADE_POLICY_DESIRED_KEYS}
        )
    return results


def create_node_pool_upgrade_policy(
    ocm_api: OCMBaseClient, cluster_id: str, node_pool: str, spec: dict
) -> None:
    """
    Creates a new Upgrade Policy for the node pool plane
    """
    ocm_api.post(
        f"{build_cluster_url(cluster_id)}/node_pools/{node_pool}/upgrade_policies", spec
    )


#
# VERSION AGREEMENTS
#


def create_version_agreement(
    ocm_api: OCMBaseClient, gate_id: str, cluster_id: str
) -> dict[str, Union[str, bool]]:
    return ocm_api.post(
        f"{build_cluster_url(cluster_id)}/gate_agreements",
        {"version_gate": {"id": gate_id}},
    )


def get_version_agreement(
    ocm_api: OCMBaseClient, cluster_id: str
) -> list[dict[str, Any]]:
    agreements = []
    for item in ocm_api.get_paginated(
        f"{build_cluster_url(cluster_id)}/gate_agreements"
    ):
        agreements.append(item)
    return agreements


def get_version_gates(ocm_api: OCMBaseClient) -> list[OCMVersionGate]:
    return [
        OCMVersionGate(**g)
        for g in ocm_api.get_paginated("/api/clusters_mgmt/v1/version_gates")
    ]
