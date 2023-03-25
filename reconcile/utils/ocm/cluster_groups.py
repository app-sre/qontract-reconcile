from enum import Enum

from reconcile.utils.ocm_base_client import OCMBaseClient


class OCMClusterGroup(Enum):
    """
    Cluster groups managable by OCM.
    """

    DEDICATED_ADMINS = "dedicated-admins"
    CLUSTER_ADMIN = "cluster-admins"


def add_user_to_cluster_group(
    ocm_api: OCMBaseClient,
    cluster_id: str,
    group: OCMClusterGroup,
    user_name: str,
) -> None:
    """
    Add a user to a cluster group.
    """
    ocm_api.post(
        build_cluster_group_users_url(cluster_id, group),
        {"id": user_name},
    )


def delete_user_from_cluster_group(
    ocm_api: OCMBaseClient,
    cluster_id: str,
    group: OCMClusterGroup,
    user_name: str,
) -> None:
    """
    Remove a user from a cluster group.
    """
    ocm_api.delete(build_cluster_group_user_url(cluster_id, group, user_name))


def get_cluster_groups(
    ocm_api: OCMBaseClient, cluster_id: str
) -> dict[OCMClusterGroup, set[str]]:
    """
    Returns a dictionary of cluster groups and the users that belong to them.
    """
    cluster_groups: dict[OCMClusterGroup, set[str]] = {}
    for group in ocm_api.get_paginated(
        build_cluster_groups_url(cluster_id), max_page_size=10
    ):
        cluster_groups[OCMClusterGroup(group["id"])] = {
            user["id"]
            for user in group.get("users", {}).get("items", [])
            if user.get("kind") == "User"
        }
    return cluster_groups


def build_cluster_groups_url(cluster_id: str) -> str:
    return f"/api/clusters_mgmt/v1/clusters/{cluster_id}/groups"


def build_cluster_group_users_url(cluster_id: str, group: OCMClusterGroup) -> str:
    return f"{build_cluster_groups_url(cluster_id)}/{group.value}/users"


def build_cluster_group_user_url(
    cluster_id: str, group: OCMClusterGroup, user_name: str
) -> str:
    return f"{build_cluster_group_users_url(cluster_id, group)}/{user_name}"
