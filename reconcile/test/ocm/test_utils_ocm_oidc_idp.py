import json
from collections.abc import Callable
from typing import (
    Any,
    Optional,
)

import pytest
from httpretty.core import HTTPrettyRequest

from reconcile.ocm.types import OCMOidcIdp
from reconcile.test.fixtures import Fixtures
from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.ocm import OCM


@pytest.fixture
def clusters() -> list[dict[str, Any]]:
    return [Fixtures("clusters").get_anymarkup("osd_spec.json")]


@pytest.fixture
def cluster_name(clusters: list[dict[str, Any]]) -> str:
    return str(clusters[0].get("name"))


@pytest.fixture
def cluster_id(clusters: list[dict[str, Any]]) -> str:
    return str(clusters[0].get("id"))


@pytest.fixture
def oidc_idp(cluster_name: str) -> OCMOidcIdp:
    return OCMOidcIdp(
        id="idp-id",
        cluster=cluster_name,
        name="idp-name",
        client_id="client-id",
        client_secret="client-secret",
        issuer="http://issuer.com",
        email_claims=["email"],
        name_claims=["name"],
        username_claims=["username"],
        groups_claims=["groups"],
    )


@pytest.mark.parametrize("fixture_name", ["full", "minimal"])
def test_ocm_get_oidc_idps(
    fixture_name: str,
    fx: Fixtures,
    ocm: OCM,
    cluster_name: str,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_ocm_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
) -> None:
    fixture = fx.get_anymarkup(f"oidc/get_{fixture_name}.yml")
    register_ocm_url_responses([OcmUrl(**i) for i in fixture["urls"]])

    assert ocm.get_oidc_idps(cluster_name) == [
        OCMOidcIdp(**fixture["expected_return_value"])
    ]
    assert find_ocm_http_request(
        "GET", "/api/clusters_mgmt/v1/clusters/osd-cluster-id/identity_providers"
    )


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
    ocm: OCM,
    oidc_idp: OCMOidcIdp,
    cluster_id: str,
    register_ocm_url_callback: Callable[[str, str, Callable], None],
) -> None:
    url = f"/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers"
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

    def request_callback(
        request: HTTPrettyRequest, uri: str, response_headers: dict[str, str]
    ) -> tuple[int, dict, str]:
        assert request.headers.get("Content-Type") == "application/json"
        assert json.loads(request.body) == request_data
        return (201, response_headers, json.dumps({}))

    register_ocm_url_callback("POST", url, request_callback)
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
    ocm: OCM,
    oidc_idp: OCMOidcIdp,
    cluster_id: str,
    register_ocm_url_callback: Callable[[str, str, Callable], None],
) -> None:
    url = f"/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers/idp-id-1"
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

    def request_callback(
        request: HTTPrettyRequest, uri: str, response_headers: dict[str, str]
    ) -> tuple[int, dict, str]:
        assert request.headers.get("Content-Type") == "application/json"
        assert json.loads(request.body) == request_data
        return (201, response_headers, json.dumps({}))

    register_ocm_url_callback("PATCH", url, request_callback)
    ocm.update_oidc_idp("idp-id-1", oidc_idp)


def test_ocm_delete_idp(
    ocm: OCM,
    cluster_name: str,
    cluster_id: str,
    register_ocm_url_callback: Callable[[str, str, Callable], None],
) -> None:
    url = f"/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers/idp-id-1"

    def request_callback(
        request: HTTPrettyRequest, uri: str, response_headers: dict[str, str]
    ) -> tuple[int, dict, str]:
        return (201, response_headers, json.dumps({}))

    register_ocm_url_callback("DELETE", url, request_callback)
    ocm.delete_idp(cluster_name, "idp-id-1")
