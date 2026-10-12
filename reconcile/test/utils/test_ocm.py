from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from reconcile.utils.ocm import OCM, OCMMap
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import VaultSecretRef

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def ocm_url() -> str:
    return "http://ocm.test"


@pytest.fixture
def cluster() -> str:
    return "cluster-1"


@pytest.fixture
def cluster_id(cluster: str) -> str:
    return f"{cluster}-id"


@pytest.fixture
def ocm(mocker: MockerFixture, ocm_url: str, cluster: str, cluster_id: str) -> OCM:
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_access_token")
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_request_headers")
    mocker.patch.object(OCM, "_init_clusters")
    mocker.patch.object(OCM, "_init_version_gates")
    ocm_client = OCMBaseClient("url", "tid", "turl", "cid")
    ocm = OCM("name", "org_id", "prod", ocm_client)
    ocm._ocm_client._url = ocm_url
    ocm.cluster_ids = {cluster: cluster_id}
    return ocm


def test_get_cluster_aws_account_id_none(mocker: MockerFixture, ocm: OCM) -> None:
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = []
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result is None


def test_get_cluster_aws_account_id_ok(mocker: MockerFixture, ocm: OCM) -> None:
    console_url = (
        "https://signin.aws.amazon.com/switchrole?account=12345&roleName=role-1"
    )
    expected = "12345"
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = [(None, None, None, console_url)]
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result == expected


@pytest.fixture
def clusters_by_readiness() -> list[tuple[dict[str, Any], bool]]:
    return [
        (
            {
                "product": {"id": "osd"},
                "managed": False,
                "state": "ready",
                "storage_quota": 42,
            },
            False,
        ),
        (
            {
                "product": {"id": "osd"},
                "managed": True,
                "state": "ready",
                "storage_quota": 42,
            },
            True,
        ),
        (
            {
                "product": "osd",
                "managed": True,
                "state": "not ready",
                "storage_quota": 42,
            },
            False,
        ),
        # ROSA-like cluster
        ({"product": {"id": "rosa"}, "managed": True, "state": "ready"}, True),
    ]


def test__ready_for_app_interface(
    clusters_by_readiness: list[tuple[dict[str, Any], bool]], ocm: OCM
) -> None:
    for cluster, readiness in clusters_by_readiness:
        assert ocm._ready_for_app_interface(cluster) == readiness


@pytest.fixture
def legacy_ocm_info() -> dict[str, Any]:
    """Shape produced by the legacy dict-based CLUSTERS_QUERY, CLUSTER_PEERING_QUERY
    and OCM_QUERY in reconcile/queries.py, which only select path/field/format/version
    for accessTokenClientSecret (no `url`).
    """
    return {
        "name": "ocm-instance",
        "orgId": "org-id",
        "accessTokenClientId": "client-id",
        "accessTokenUrl": "https://sso.example.com/token",
        "accessTokenClientSecret": {
            "path": "some/vault/path",
            "field": "client_secret",
            "format": None,
            "version": None,
        },
        "environment": {
            "name": "prod",
            "url": "https://api.openshift.com",
            "accessTokenClientId": "env-client-id",
            "accessTokenUrl": "https://sso.example.com/token",
            "accessTokenClientSecret": {
                "path": "env/vault/path",
                "field": "client_secret",
                "format": None,
                "version": None,
            },
        },
    }


def test_ocmmap_init_ocm_client_with_legacy_dict_missing_url(
    mocker: MockerFixture, legacy_ocm_info: dict[str, Any]
) -> None:
    """Regression test: reconcile/queries.py's legacy dict-based OCM queries never
    select `url` for accessTokenClientSecret. OCMMap.init_ocm_client() must build
    the OCM API client's secret reference without depending on the generated
    (reconcile.gql_definitions) VaultSecret model, which now requires `url`.
    """
    init_ocm_base_client_mock = mocker.patch(
        "reconcile.utils.ocm.ocm.init_ocm_base_client", autospec=True
    )
    mocker.patch("reconcile.utils.ocm.ocm.OCM", autospec=True)

    OCMMap(ocms=[legacy_ocm_info])

    init_ocm_base_client_mock.assert_called_once()
    cfg = init_ocm_base_client_mock.call_args.kwargs["cfg"]
    assert cfg.access_token_client_secret == VaultSecretRef(
        path="some/vault/path",
        field="client_secret",
        version=None,
        q_format=None,
    )
