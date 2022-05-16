import json
import pytest
import httpretty
from httpretty.core import HTTPrettyRequest

from reconcile.utils.ocm import OCM


@pytest.fixture
def ocm(mocker):
    mocker.patch("reconcile.utils.ocm.OCM._init_access_token")
    mocker.patch("reconcile.utils.ocm.OCM._init_request_headers")
    mocker.patch("reconcile.utils.ocm.OCM._init_clusters")
    mocker.patch("reconcile.utils.ocm.OCM._init_blocked_versions")
    mocker.patch("reconcile.utils.ocm.OCM._init_version_gates")
    return OCM("name", "url", "tid", "turl", "ot")


def test_get_cluster_aws_account_id_none(mocker, ocm):
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = []
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result is None


def test_get_cluster_aws_account_id_ok(mocker, ocm):
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
def clusters_by_readiness():
    return [
        ({"managed": False, "state": "ready", "storage_quota": 42}, False),
        ({"managed": True, "state": "ready", "storage_quota": 42}, True),
        ({"managed": True, "state": "not ready", "storage_quota": 42}, False),
        # ROSA-like cluster
        ({"managed": True, "state": "ready"}, False),
    ]


def test__ready_for_app_interface(clusters_by_readiness, ocm):
    for cluster, readiness in clusters_by_readiness:
        assert ocm._ready_for_app_interface(cluster) == readiness


def test_get_version_gate(ocm):
    ocm.version_gates = [
        {"version_raw_id_prefix": "4.9", "sts_only": True},
        {"version_raw_id_prefix": "4.9", "sts_only": False},
        {"version_raw_id_prefix": "4.10", "sts_only": False},
    ]
    gates = ocm.get_version_gates("4.9")
    assert gates == [{"version_raw_id_prefix": "4.9", "sts_only": False}]
    gates = ocm.get_version_gates("4.9", sts_only=True)
    assert gates == [{"version_raw_id_prefix": "4.9", "sts_only": True}]
    assert len(ocm.get_version_gates("4.8")) == 0


def test__get_json_pagination(ocm):
    ocm.url = "http://ocm.test"
    call_cnt = 0

    def paginated_response(request: HTTPrettyRequest, url, response_headers):
        nonlocal call_cnt
        call_cnt = call_cnt + 1
        # Return four pages, last one only partially filled
        if "page" not in request.querystring:
            p = 1
        else:
            p = int(request.querystring["page"][0])

        if p <= 3:
            items = [{"id": x} for x in range(0, 100)]
        elif p == 4:
            items = [{"id": x} for x in range(0, 11)]
        else:
            items = []
        body = {"kind": "TestList", "page": p, "items": items, "size": len(items)}

        return [200, response_headers, json.dumps(body)]

    httpretty.enable()
    httpretty.register_uri(
        httpretty.GET, "http://ocm.test/api", body=paginated_response
    )

    resp = ocm._get_json("/api")

    httpretty.disable()

    assert "kind" in resp
    assert "total" in resp
    assert "items" in resp
    assert len(resp["items"]) == 311
    assert len(resp["items"]) == resp["total"]
    assert call_cnt == 4


def test__get_json_empty_list(ocm: OCM):
    ocm.url = "http://ocm.test"
    httpretty.enable()
    httpretty.register_uri(
        httpretty.GET,
        "http://ocm.test/api",
        body=json.dumps({"kind": "TestList", "page": 1, "size": 0, "total": 0}),
    )

    resp = ocm._get_json("/api")
    httpretty.disable()
    assert "items" not in resp
    assert resp["total"] == 0


def test__get_json_simple_list(ocm: OCM):
    ocm.url = "http://ocm.test"
    httpretty.enable()
    httpretty.register_uri(
        httpretty.GET,
        "http://ocm.test/api",
        body=json.dumps({"kind": "TestList", "items": {"foo": "bar"}}),
    )

    resp = ocm._get_json("/api")
    httpretty.disable()
    assert "items" in resp


def test__get_json(ocm):
    ocm.url = "http://ocm.test"

    httpretty.enable()
    httpretty.register_uri(
        httpretty.GET, "http://ocm.test/api", body=json.dumps({"kind": "test", "id": 1})
    )
    x = ocm._get_json("/api")
    httpretty.disable()

    assert x["id"] == 1
