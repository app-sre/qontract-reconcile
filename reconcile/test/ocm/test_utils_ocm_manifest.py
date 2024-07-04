from collections.abc import Callable
from typing import Any

from pytest_mock import MockerFixture
from werkzeug import Request

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm import manifests
from reconcile.utils.ocm.manifests import (
    create_manifest,
    patch_manifest,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_manifest(cluster_id: str, manifest_id: str) -> dict[str, Any]:
    return {
        "kind": "Manifest",
        "href": f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/manifests/ext-dynatrace-tokens",
        "id": f"{manifest_id}",
        "resources": [],
    }


def test_utils_get_manifests(
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    get_manifests_call = mocker.patch.object(
        manifests, "get_manifests", wraps=manifests.get_manifests
    )
    cluster_id = "123abc"
    manifest_list_kind_value = "ManifestList"
    manifest_a = {
        "kind": "Manifest",
        "id": "manifest1",
    }
    manifest_b = {
        "kind": "Manifest",
        "id": "manifest2",
    }
    register_ocm_url_responses([
        OcmUrl(
            method="GET",
            uri=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/manifests",
        ).add_paginated_get_response(
            page=1,
            size=2,
            total=2,
            kind=manifest_list_kind_value,
            items=[
                manifest_a,
                manifest_b,
            ],
        )
    ])

    response = manifests.get_manifests(ocm_client=ocm_api, cluster_id=cluster_id)

    assert [item for item in response] == [manifest_a, manifest_b]

    get_manifests_call.assert_called_once_with(
        ocm_client=ocm_api, cluster_id=cluster_id
    )


def test_utils_get_manifest(
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    get_manifest_call = mocker.patch.object(
        manifests, "get_manifest", wraps=manifests.get_manifest
    )
    cluster_id = "123abc"
    manifest_id = "xyz"
    manifest_kind_value = "Manifest"
    register_ocm_url_responses([
        OcmUrl(
            method="GET",
            uri=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/manifests/{manifest_id}",
        ).add_get_response(id=manifest_id, resources=[], kind=manifest_kind_value)
    ])

    response = manifests.get_manifest(
        ocm_client=ocm_api, cluster_id=cluster_id, manifest_id=manifest_id
    )

    assert response["kind"] == manifest_kind_value

    get_manifest_call.assert_called_once_with(
        ocm_client=ocm_api, cluster_id=cluster_id, manifest_id=manifest_id
    )


def test_create_manifest(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str], list[Request]],
) -> None:
    cluster_id = "123abc"
    manifest_id = "xyz"
    register_ocm_url_responses([
        OcmUrl(
            method="POST",
            uri=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/manifests",
        )
    ])

    create_manifest(ocm_api, cluster_id, build_manifest(cluster_id, manifest_id))

    ocm_calls = find_all_ocm_http_requests("POST")
    assert len(ocm_calls) == 1


def test_patch_manifest(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str], list[Request]],
) -> None:
    cluster_id = "123abc"
    manifest_id = "xyz"
    manifest = build_manifest(cluster_id, manifest_id)

    register_ocm_url_responses([
        OcmUrl(
            method="PATCH",
            uri=f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/manifests/{manifest_id}",
        )
    ])

    manifest["resources"] = [{"kind": "Secret"}]
    patch_manifest(ocm_api, cluster_id, manifest_id, manifest)

    ocm_calls = find_all_ocm_http_requests("PATCH")
    assert len(ocm_calls) == 1
