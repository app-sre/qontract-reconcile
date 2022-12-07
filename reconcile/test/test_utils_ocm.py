import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any
from urllib.parse import urljoin

import httpretty
import pytest
from httpretty.core import HTTPrettyRequest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from reconcile.ocm.types import OCMOidcIdp
from reconcile.test.fixtures import Fixtures
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.ocm import (
    OCM,
    OCMMap,
    Sector,
    SectorConfigError,
    SectorWeakReference,
)


class OcmUrl(BaseModel):
    name: str
    uri: str
    method: str = "POST"
    responses: list[Any] = []


@pytest.fixture
def configure_httpretty(httpretty: httpretty, ocm_url: str) -> Callable:
    def f(urls: list[OcmUrl]) -> int:
        i = 0
        for url in urls:
            i += len(url.responses) or 1
            httpretty.register_uri(
                url.method.upper(),
                urljoin(ocm_url, url.uri),
                responses=[
                    httpretty.Response(body=json.dumps(r)) for r in url.responses
                ],
                content_type="text/json",
            )
        return i

    return f


@pytest.fixture
def fx():
    return Fixtures("ocm")


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
def oidc_idp(cluster: str) -> OCMOidcIdp:
    return OCMOidcIdp(
        id="idp-id",
        cluster=cluster,
        name="idp-name",
        client_id="client-id",
        client_secret="client-secret",
        issuer="http://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=["groups"],
    )


@pytest.fixture
def ocm(mocker: MockerFixture, ocm_url: str, cluster: str, cluster_id: str) -> OCM:
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_access_token")
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_request_headers")
    mocker.patch("reconcile.utils.ocm.OCM.whoami")
    mocker.patch("reconcile.utils.ocm.OCM._init_clusters")
    mocker.patch("reconcile.utils.ocm.OCM._init_blocked_versions")
    mocker.patch("reconcile.utils.ocm.OCM._init_version_gates")
    ocm = OCM("name", "url", "tid", "turl", "ot")
    ocm._ocm_client._url = ocm_url
    ocm.cluster_ids = {cluster: cluster_id}
    return ocm


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
    ocm._ocm_client._url = "http://ocm.test"
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
    ocm._ocm_client._url = "http://ocm.test"
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
    ocm._ocm_client._url = "http://ocm.test"
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
    ocm._ocm_client._url = "http://ocm.test"

    httpretty.enable()
    httpretty.register_uri(
        httpretty.GET, "http://ocm.test/api", body=json.dumps({"kind": "test", "id": 1})
    )
    x = ocm._get_json("/api")
    httpretty.disable()

    assert x["id"] == 1


def test_sector_validate_dependencies(ocm):
    sector1 = Sector(
        name="sector1", ocm=ocm, cluster_infos=[], dependencies_refs=[], dependencies=[]
    )
    sector2 = Sector(
        name="sector2",
        ocm=ocm,
        cluster_infos=[],
        dependencies_refs=[],
        dependencies=[sector1],
    )
    sector3 = Sector(
        name="sector3",
        ocm=ocm,
        cluster_infos=[],
        dependencies_refs=[],
        dependencies=[sector2],
    )
    assert sector3.validate_dependencies()

    # zero-level loop sector1 -> sector1
    sector1 = Sector(
        name="sector1", ocm=ocm, cluster_infos=[], dependencies_refs=[], dependencies=[]
    )
    sector1.dependencies = [sector1]
    with pytest.raises(SectorConfigError):
        sector1.validate_dependencies()

    # single-level loop sector2 -> sector1 -> sector2
    sector1 = Sector(
        name="sector1", ocm=ocm, cluster_infos=[], dependencies_refs=[], dependencies=[]
    )
    sector2 = Sector(
        name="sector2",
        ocm=ocm,
        cluster_infos=[],
        dependencies_refs=[],
        dependencies=[sector1],
    )
    sector1.dependencies = [sector2]
    with pytest.raises(SectorConfigError):
        sector2.validate_dependencies()

    # greater-level loop sector3 -> sector2 -> sector1 -> sector3
    sector1 = Sector(
        name="sector1", ocm=ocm, cluster_infos=[], dependencies_refs=[], dependencies=[]
    )
    sector2 = Sector(
        name="sector2",
        ocm=ocm,
        cluster_infos=[],
        dependencies_refs=[],
        dependencies=[sector1],
    )
    sector3 = Sector(
        name="sector3",
        ocm=ocm,
        cluster_infos=[],
        dependencies_refs=[],
        dependencies=[sector2],
    )
    sector1.dependencies = [sector3]
    with pytest.raises(SectorConfigError):
        sector3.validate_dependencies()


def test_ocm_map_upgrade_policies_sector(ocm, mocker):
    mocker.patch("reconcile.utils.ocm.SecretReader")
    sectors = [
        {"name": "s1"},
        {"name": "s2", "dependencies": [{"name": "s1"}]},
        {"name": "s3", "dependencies": [{"ocm": {"name": "ocm1"}, "name": "s1"}]},
        {"name": "s4", "dependencies": [{"ocm": {"name": "ocm1"}, "name": "*"}]},
    ]
    ocm1_info = {
        "name": "ocm1",
        "sectors": sectors,
        "accessTokenClientId": "atci",
        "accessTokenUrl": "atu",
        "accessTokenClientSecret": "atcs",
        "url": "u",
    }
    c1 = {
        "name": "c1",
        "ocm": ocm1_info,
        "upgradePolicy": {"workload": "w1"},
    }
    c2 = {
        "name": "c2",
        "ocm": ocm1_info,
        "upgradePolicy": {"workload": "w1", "conditions": {"sector": "s2"}},
    }

    # second org, using the same sector names
    ocm2_info = deepcopy(ocm1_info)
    ocm2_info["name"] = "ocm2"
    c3 = {
        "name": "c3",
        "ocm": ocm2_info,
        "upgradePolicy": {"workload": "w1", "conditions": {"sector": "s3"}},
    }

    mocker.patch("reconcile.utils.ocm.OCM.is_ready").return_value = True
    ocm_map = OCMMap(clusters=[c1, c2, c3])
    assert "ocm1" in ocm_map.ocm_map
    assert "ocm2" in ocm_map.ocm_map

    # all sectors are reported, even the ones without clusters
    ocm1 = ocm_map["ocm1"]
    assert len(ocm1.sectors) == 4

    ocm2 = ocm_map["ocm2"]
    assert len(ocm2.sectors) == 4

    # no dependencies
    s1 = Sector(
        name="s1", ocm=ocm1, dependencies=[], dependencies_refs=[], cluster_infos=[]
    )
    assert ocm1.sectors["s1"] == s1

    # partial dependency definition, without ocm org. defaulting to sector's org
    s1_weak = SectorWeakReference(ocm_org_name="ocm1", sector_name="s1")
    s2 = Sector(
        name="s2",
        ocm=ocm1,
        dependencies=[s1],
        dependencies_refs=[s1_weak],
        cluster_infos=[c2],
    )
    assert ocm1.sectors["s2"] == s2

    # full dependency definition, including ocm org
    s3 = Sector(
        name="s3",
        ocm=ocm1,
        dependencies=[s1],
        dependencies_refs=[s1_weak],
        cluster_infos=[],
    )
    assert ocm1.sectors["s3"] == s3

    # wildcard dependencies report all other sectors
    wildcard_dep_ref = SectorWeakReference(ocm_org_name="ocm1", sector_name="*")
    s4 = Sector(
        name="s4",
        ocm=ocm1,
        dependencies=[s1, s2, s3],
        dependencies_refs=[wildcard_dep_ref],
        cluster_infos=[],
    )
    assert ocm1.sectors["s4"] == s4

    # cross-orgs dependency
    assert ocm2.sectors["s3"].dependencies == [s1]

    # cross-orgs wildcard dependencies
    assert ocm2.sectors["s4"].dependencies == [s1, s2, s3, s4]


@pytest.mark.parametrize("fixture_name", ["full", "minimal"])
def test_ocm_get_oidc_idps(
    fixture_name: str,
    httpretty: httpretty,
    configure_httpretty: Callable,
    fx: Fixtures,
    ocm: OCM,
    cluster: str,
) -> None:
    fixture = fx.get_anymarkup(f"oidc/get_{fixture_name}.yml")
    expected_return_value = OCMOidcIdp(**fixture["expected_return_value"])
    request_count = configure_httpretty([OcmUrl(**i) for i in fixture["urls"]])

    assert ocm.get_oidc_idps(cluster) == [expected_return_value]
    assert len(httpretty.latest_requests()) == request_count


@pytest.mark.parametrize(
    "attr, bad_value",
    [
        ("client_secret", None),
        ("email_claims", []),
        ("name_claims", []),
        ("username_claims", []),
    ],
)
def test_ocm_create_oidc_idp_must_raise_an_error(
    attr: str, bad_value: Any, ocm: OCM, oidc_idp: OCMOidcIdp
) -> None:
    setattr(oidc_idp, attr, bad_value)
    with pytest.raises(ParameterError):
        ocm.create_oidc_idp(oidc_idp)


def test_ocm_create_oidc_idp(
    httpretty: httpretty,
    ocm: OCM,
    ocm_url: str,
    oidc_idp: OCMOidcIdp,
    cluster_id: str,
) -> None:
    url = f"{ocm_url}/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers"
    request_data = {
        "type": "OpenIDIdentityProvider",
        "name": oidc_idp.name,
        "mapping_method": "claim",
        "open_id": {
            "claims": {
                "email": oidc_idp.email_claims,
                "name": oidc_idp.name_claims,
                "preferred_username": oidc_idp.username_claims,
                "groups": oidc_idp.groups_claims,
            },
            "client_id": oidc_idp.client_id,
            "client_secret": oidc_idp.client_secret,
            "issuer": oidc_idp.issuer,
        },
    }

    def request_callback(request, uri, response_headers):
        assert request.headers.get("Content-Type") == "application/json"
        assert json.loads(request.body) == request_data
        return [201, response_headers, json.dumps({})]

    httpretty.register_uri(
        httpretty.POST, url, content_type="text/json", body=request_callback
    )
    ocm.create_oidc_idp(oidc_idp)


@pytest.mark.parametrize(
    "attr, bad_value",
    [
        ("client_secret", None),
        ("email_claims", []),
        ("name_claims", []),
        ("username_claims", []),
    ],
)
def test_ocm_update_oidc_idp_must_raise_an_error(
    attr: str, bad_value: Any, ocm: OCM, oidc_idp: OCMOidcIdp
) -> None:
    setattr(oidc_idp, attr, bad_value)
    with pytest.raises(ParameterError):
        ocm.update_oidc_idp(id="1", oidc_idp=oidc_idp)


def test_ocm_update_oidc_idp(
    httpretty: httpretty,
    ocm: OCM,
    ocm_url: str,
    oidc_idp: OCMOidcIdp,
    cluster_id: str,
) -> None:
    url = f"{ocm_url}/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers/idp-id-1"
    request_data = {
        "type": "OpenIDIdentityProvider",
        "open_id": {
            "claims": {
                "email": oidc_idp.email_claims,
                "name": oidc_idp.name_claims,
                "preferred_username": oidc_idp.username_claims,
                "groups": oidc_idp.groups_claims,
            },
            "client_id": oidc_idp.client_id,
            "client_secret": oidc_idp.client_secret,
            "issuer": oidc_idp.issuer,
        },
    }

    def request_callback(request, uri, response_headers):
        assert request.headers.get("Content-Type") == "application/json"
        assert json.loads(request.body) == request_data
        return [201, response_headers, json.dumps({})]

    httpretty.register_uri(
        httpretty.PATCH, url, content_type="text/json", body=request_callback
    )
    ocm.update_oidc_idp("idp-id-1", oidc_idp)


def test_ocm_delete_idp(
    httpretty: httpretty,
    ocm: OCM,
    ocm_url: str,
    cluster: str,
    cluster_id: str,
) -> None:
    url = f"{ocm_url}/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers/idp-id-1"

    def request_callback(request, uri, response_headers):
        return [201, response_headers, json.dumps({})]

    httpretty.register_uri(httpretty.DELETE, url, body=request_callback)
    ocm.delete_idp(cluster, "idp-id-1")
