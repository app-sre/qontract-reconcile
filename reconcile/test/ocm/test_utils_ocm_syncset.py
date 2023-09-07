from collections.abc import Callable
from typing import Any

from httpretty.core import HTTPrettyRequest
from pytest_mock import MockerFixture

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm import syncsets
from reconcile.utils.ocm.syncsets import (
    create_syncset,
    patch_syncset,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_syncset(cluster_id: str, syncset_id: str) -> dict[str, Any]:
    return {
        "kind": "Syncset",
        "href": f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/syncsets/ext-dynatrace-tokens",
        "id": f"{syncset_id}",
        "resources": [],
    }


def test_utils_get_syncsets(
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    get_syncsets_call = mocker.patch.object(
        syncsets, "get_syncset", wraps=syncsets.get_syncset
    )
    cluster_id = "123abc"
    syncset_id = "xyz"
    syncset_kind_value = "Syncset"
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/syncsets/{syncset_id}",
            ).add_get_response(id=syncset_id, resources=[], kind=syncset_kind_value)
        ]
    )

    response = syncsets.get_syncset(
        ocm_client=ocm_api, cluster_id=cluster_id, syncset_id=syncset_id
    )

    assert response["kind"] == syncset_kind_value

    get_syncsets_call.assert_called_once_with(
        ocm_client=ocm_api, cluster_id=cluster_id, syncset_id=syncset_id
    )


def test_create_syncset(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str], list[HTTPrettyRequest]],
) -> None:
    cluster_id = "123abc"
    syncset_id = "xyz"
    register_ocm_url_responses(
        [
            OcmUrl(
                method="POST",
                uri=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/syncsets",
            )
        ]
    )

    create_syncset(ocm_api, cluster_id, build_syncset(cluster_id, syncset_id))

    ocm_calls = find_all_ocm_http_requests("POST")
    assert len(ocm_calls) == 1


def test_patch_syncset(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str], list[HTTPrettyRequest]],
) -> None:
    cluster_id = "123abc"
    syncset_id = "xyz"
    syncset = build_syncset(cluster_id, syncset_id)

    register_ocm_url_responses(
        [
            OcmUrl(
                method="PATCH",
                uri=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/syncsets/{syncset_id}",
            )
        ]
    )

    syncset["resources"] = [{"kind": "Secret"}]
    patch_syncset(ocm_api, cluster_id, syncset_id, syncset)

    ocm_calls = find_all_ocm_http_requests("PATCH")
    assert len(ocm_calls) == 1
