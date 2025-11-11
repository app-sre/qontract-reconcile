from reconcile.utils.ocm.base import (
    OCMClusterGroup,
    OCMClusterGroupId,
    OCMClusterUser,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def add_user_to_cluster_group(
    ocm_api: OCMBaseClient,
    cluster_id: str,
    group: OCMClusterGroupId,
    user_name: str,
) -> None:
    """
    Add a user to a cluster group.
    """
    ocm_api.post(
        build_cluster_group_users_url(cluster_id, group),
        OCMClusterUser(id=user_name).dict(by_alias=True),
    )


def delete_user_from_cluster_group(
    ocm_api: OCMBaseClient,
    cluster_id: str,
    group: OCMClusterGroupId,
    user_name: str,
) -> None:
    """
    Remove a user from a cluster group.
    """
    ocm_api.delete(build_cluster_group_user_url(cluster_id, group, user_name))


def get_cluster_groups(
    ocm_api: OCMBaseClient, cluster_id: str
) -> dict[OCMClusterGroupId, OCMClusterGroup]:
    """
    Returns a dictionary of cluster groups, containg the users in each group.
    """
    cluster_groups: dict[OCMClusterGroupId, OCMClusterGroup] = {}
    for group_dict in ocm_api.get_paginated(
        build_cluster_groups_url(cluster_id), max_page_size=10
    ):
        group = OCMClusterGroup(**group_dict)
        cluster_groups[group.id] = group
    return cluster_groups


def build_cluster_groups_url(cluster_id: str) -> str:
    return f"/api/clusters_mgmt/v1/clusters/{cluster_id}/groups"


def build_cluster_group_users_url(cluster_id: str, group: OCMClusterGroupId) -> str:
    return f"{build_cluster_groups_url(cluster_id)}/{group.value}/users"


def build_cluster_group_user_url(
    cluster_id: str, group: OCMClusterGroupId, user_name: str
) -> str:
    return f"{build_cluster_group_users_url(cluster_id, group)}/{user_name}"
