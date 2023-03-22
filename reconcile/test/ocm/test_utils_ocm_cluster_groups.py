import httpretty as httpretty_module

from reconcile.test.ocm.conftest import (
    register_ocm_delete_request,
    register_ocm_get_list_request,
    register_ocm_post_request,
)
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.ocm.cluster_groups import (
    OCMClusterGroup,
    add_user_to_cluster_group,
    build_cluster_group_user_url,
    build_cluster_group_users_url,
    build_cluster_groups_url,
    delete_user_from_cluster_group,
    get_cluster_groups,
)


def test_get_cluster_groups(
    ocm_api: OCMBaseClient,
    httpretty: httpretty_module,
):
    cluster_id = "cluster_id"
    register_ocm_get_list_request(
        ocm_api,
        httpretty,
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
    httpretty: httpretty_module,
):
    cluster_id = "cluster_id"
    user_name = "user-to-add"
    group = OCMClusterGroup.DEDICATED_ADMINS
    add_user_url = build_cluster_group_users_url(cluster_id, group)

    register_ocm_post_request(ocm_api, httpretty, add_user_url)
    add_user_to_cluster_group(
        ocm_api=ocm_api,
        cluster_id=cluster_id,
        group=group,
        user_name=user_name,
    )

    assert next(
        (
            req
            for req in httpretty.latest_requests()
            if req.method == "POST" and req.path == add_user_url
        ),
        None,
    )


def test_delete_user_from_cluster_group(
    ocm_api: OCMBaseClient,
    httpretty: httpretty_module,
):
    cluster_id = "cluster_id"
    user_name = "user-to-delete"
    group = OCMClusterGroup.DEDICATED_ADMINS
    user_delete_url = build_cluster_group_user_url(cluster_id, group, user_name)

    register_ocm_delete_request(ocm_api, httpretty, user_delete_url)
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
