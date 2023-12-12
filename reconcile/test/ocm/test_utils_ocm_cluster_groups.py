import json
from collections.abc import Callable
from typing import Optional

import httpretty as httpretty_module
from httpretty.core import HTTPrettyRequest

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm.base import (
    OCMClusterGroup,
    OCMClusterGroupId,
    OCMClusterUser,
    OCMClusterUserList,
)
from reconcile.utils.ocm.cluster_groups import (
    add_user_to_cluster_group,
    build_cluster_group_user_url,
    build_cluster_group_users_url,
    build_cluster_groups_url,
    delete_user_from_cluster_group,
    get_cluster_groups,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_ocm_cluster_group(
    id: OCMClusterGroupId, user_ids: set[str]
) -> OCMClusterGroup:
    return OCMClusterGroup(
        id=id,
        users=OCMClusterUserList(
            items=[OCMClusterUser(id=user_id) for user_id in user_ids]
        ),
    )


def test_get_cluster_groups(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    cluster_id = "cluster_id"
    register_ocm_url_responses([
        OcmUrl(
            method="GET", uri=build_cluster_groups_url(cluster_id)
        ).add_list_response(
            [
                build_ocm_cluster_group(
                    OCMClusterGroupId.DEDICATED_ADMINS, {"user-1", "user-2"}
                ),
                build_ocm_cluster_group(
                    OCMClusterGroupId.CLUSTER_ADMINS, {"user-3", "user-4"}
                ),
            ],
        ),
    ])
    groups = get_cluster_groups(
        ocm_api=ocm_api,
        cluster_id=cluster_id,
    )
    assert OCMClusterGroupId.DEDICATED_ADMINS in groups
    assert groups[OCMClusterGroupId.DEDICATED_ADMINS].user_ids() == {"user-1", "user-2"}
    assert OCMClusterGroupId.CLUSTER_ADMINS in groups
    assert groups[OCMClusterGroupId.CLUSTER_ADMINS].user_ids() == {"user-3", "user-4"}


def test_add_user_to_cluster_group(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_ocm_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
) -> None:
    cluster_id = "cluster_id"
    user_name = "user-to-add"
    group = OCMClusterGroupId.DEDICATED_ADMINS
    add_user_url = build_cluster_group_users_url(cluster_id, group)
    register_ocm_url_responses([OcmUrl(uri=add_user_url)])

    add_user_to_cluster_group(
        ocm_api=ocm_api,
        cluster_id=cluster_id,
        group=group,
        user_name=user_name,
    )

    post_request = find_ocm_http_request("POST", add_user_url)
    assert isinstance(post_request, HTTPrettyRequest)
    assert json.loads(post_request.body).get("id") == user_name


def test_delete_user_from_cluster_group(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    httpretty: httpretty_module,
) -> None:
    cluster_id = "cluster_id"
    user_name = "user-to-delete"
    group = OCMClusterGroupId.DEDICATED_ADMINS
    user_delete_url = build_cluster_group_user_url(cluster_id, group, user_name)
    register_ocm_url_responses([OcmUrl(method="DELETE", uri=user_delete_url)])

    delete_user_from_cluster_group(
        ocm_api=ocm_api,
        cluster_id=cluster_id,
        group=group,
        user_name=user_name,
    )

    assert next(
        (
            req
            for req in httpretty.latest_requests()
            if req.method == "DELETE" and req.path == user_delete_url
        ),
        None,
    )
