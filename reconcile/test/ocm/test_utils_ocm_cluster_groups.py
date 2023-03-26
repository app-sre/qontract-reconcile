import json
from typing import Any, Callable, Optional
import httpretty as httpretty_module
from httpretty.core import HTTPrettyRequest


from reconcile.utils.ocm.cluster_groups import (
    OCMClusterGroup,
    add_user_to_cluster_group,
    build_cluster_group_user_url,
    build_cluster_group_users_url,
    build_cluster_groups_url,
    delete_user_from_cluster_group,
    get_cluster_groups,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def test_get_cluster_groups(
    ocm_api: OCMBaseClient,
    register_ocm_get_list_handler: Callable[[str, Optional[Any]], None],
):
    cluster_id = "cluster_id"
    register_ocm_get_list_handler(
        build_cluster_groups_url(cluster_id),
        [
            {
                "id": OCMClusterGroup.DEDICATED_ADMINS,
                "users": {
                    "items": [
                        {
                            "kind": "User",
                            "id": "user-1",
                        },
                        {
                            "kind": "User",
                            "id": "user-2",
                        },
                    ]
                },
            },
            {
                "id": OCMClusterGroup.CLUSTER_ADMIN,
                "users": {
                    "items": [
                        {
                            "kind": "User",
                            "id": "user-3",
                        },
                        {
                            "kind": "User",
                            "id": "user-4",
                        },
                    ]
                },
            },
        ],
    )
    groups = get_cluster_groups(
        ocm_api=ocm_api,
        cluster_id=cluster_id,
    )
    assert OCMClusterGroup.DEDICATED_ADMINS in groups
    assert groups[OCMClusterGroup.DEDICATED_ADMINS] == {"user-1", "user-2"}
    assert OCMClusterGroup.CLUSTER_ADMIN in groups
    assert groups[OCMClusterGroup.CLUSTER_ADMIN] == {"user-3", "user-4"}


def test_add_user_to_cluster_group(
    ocm_api: OCMBaseClient,
    register_ocm_request_handler: Callable[[str, str, Optional[Any]], None],
    find_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
):
    cluster_id = "cluster_id"
    user_name = "user-to-add"
    group = OCMClusterGroup.DEDICATED_ADMINS
    add_user_url = build_cluster_group_users_url(cluster_id, group)
    register_ocm_request_handler("POST", add_user_url, None)

    add_user_to_cluster_group(
        ocm_api=ocm_api,
        cluster_id=cluster_id,
        group=group,
        user_name=user_name,
    )

    post_request = find_http_request("POST", add_user_url)
    assert isinstance(post_request, HTTPrettyRequest)
    assert json.loads(post_request.body).get("id") == user_name


def test_delete_user_from_cluster_group(
    ocm_api: OCMBaseClient,
    register_ocm_request_handler: Callable[[str, str, Optional[Any]], None],
    httpretty: httpretty_module,
):
    cluster_id = "cluster_id"
    user_name = "user-to-delete"
    group = OCMClusterGroup.DEDICATED_ADMINS
    user_delete_url = build_cluster_group_user_url(cluster_id, group, user_name)
    register_ocm_request_handler("DELETE", user_delete_url, None)

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
