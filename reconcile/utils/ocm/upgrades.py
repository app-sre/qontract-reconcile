from typing import Any, TypedDict

from reconcile.utils.ocm.base import OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient


class UpgradePolicy(TypedDict):
    id: str | None
    next_run: str | None
    schedule: str | None
    schedule_type: str
    state: str | None
    version: str


def _build_upgrade_policy(
    response: dict,
    state: str | None,
) -> UpgradePolicy:
    return UpgradePolicy(
        id=response.get("id"),
        schedule_type=response["schedule_type"],
        schedule=response.get("schedule"),
        next_run=response.get("next_run"),
        version=response["version"],
        state=state,
    )


def build_cluster_url(cluster_id: str) -> str:
    return f"/api/clusters_mgmt/v1/clusters/{cluster_id}"


#
# UPGRADE POLICIES
#


def get_upgrade_policies(
    ocm_api: OCMBaseClient,
    cluster_id: str,
) -> list[UpgradePolicy]:
    """Returns a list of details of Upgrade Policies

    :param ocm_api: OCM API client
    :param cluster_id: cluster id

    :return: list of UpgradePolicy
    """
    return [
        _build_upgrade_policy(
            policy,
            state=get_upgrade_policy_state(ocm_api, cluster_id, policy["id"]),
        )
        for policy in ocm_api.get_paginated(
            f"{build_cluster_url(cluster_id)}/upgrade_policies"
        )
    ]


def get_upgrade_policy_state(
    ocm_api: OCMBaseClient, cluster_id: str, upgrade_policy_id: str
) -> str | None:
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
    ocm_api: OCMBaseClient,
    cluster_id: str,
) -> list[UpgradePolicy]:
    """
    Returns a list of details of Upgrade Policies
    """
    return [
        _build_upgrade_policy(
            policy,
            state=policy.get("state", {}).get("value"),
        )
        for policy in ocm_api.get_paginated(
            f"{build_cluster_url(cluster_id)}/control_plane/upgrade_policies"
        )
    ]


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
) -> list[UpgradePolicy]:
    """
    Returns a list of details of Upgrade Policies
    """
    return [
        _build_upgrade_policy(
            policy,
            state=policy.get("state", {}).get("value"),
        )
        for policy in ocm_api.get_paginated(
            f"{build_cluster_url(cluster_id)}/node_pools/{node_pool}/upgrade_policies"
        )
    ]


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
) -> dict[str, str | bool]:
    return ocm_api.post(
        f"{build_cluster_url(cluster_id)}/gate_agreements",
        {"version_gate": {"id": gate_id}},
    )


def get_version_agreement(
    ocm_api: OCMBaseClient, cluster_id: str
) -> list[dict[str, Any]]:
    return list(
        ocm_api.get_paginated(f"{build_cluster_url(cluster_id)}/gate_agreements")
    )


def get_version_gates(ocm_api: OCMBaseClient) -> list[OCMVersionGate]:
    return [
        OCMVersionGate(**g)
        for g in ocm_api.get_paginated("/api/clusters_mgmt/v1/version_gates")
    ]
