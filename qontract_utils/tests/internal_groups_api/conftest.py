from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
from pytest_httpserver import HTTPServer
from qontract_utils.internal_groups_api.api import InternalGroupsApi
from qontract_utils.internal_groups_api.client import InternalGroupsClient

FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(relative: str) -> dict:
    return json.loads((FIXTURES / relative).read_text())


@pytest.fixture
def group_name() -> str:
    return "test-group"


@pytest.fixture
def non_existent_group_name() -> str:
    return "does-not-exist"


@pytest.fixture
def internal_groups_url(httpserver: HTTPServer) -> str:
    return httpserver.url_for("")


@pytest.fixture
def issuer_url() -> str:
    return "http://fake-issuer-url-server.com"


@pytest.fixture
def client_id() -> str:
    return "client_id"


@pytest.fixture
def client_secret() -> str:
    return "client_secret"


@pytest.fixture
def internal_groups_server_full_api_response(
    httpserver: HTTPServer,
    group_name: str,
    non_existent_group_name: str,
) -> None:
    for method in ["get", "post"]:
        httpserver.expect_request("/v1/groups/", method=method).respond_with_json(
            _load_json("v1/groups/post.json")
        )
    httpserver.expect_request(
        f"/v1/groups/{group_name}", method="get"
    ).respond_with_json(_load_json(f"v1/groups/{group_name}/get.json"))
    httpserver.expect_request(
        f"/v1/groups/{group_name}", method="patch"
    ).respond_with_json(_load_json(f"v1/groups/{group_name}/patch.json"))
    httpserver.expect_request(
        f"/v1/groups/{group_name}", method="delete"
    ).respond_with_data(status=204)
    for method in ["get", "put", "patch", "delete"]:
        httpserver.expect_request(
            f"/v1/groups/{non_existent_group_name}", method=method
        ).respond_with_data(status=404)


@pytest.fixture
def internal_groups_api_minimal(
    internal_groups_url: str, issuer_url: str, client_id: str, client_secret: str
) -> InternalGroupsApi:
    InternalGroupsApi.__enter__ = lambda self: self  # type: ignore[method-assign]
    api = InternalGroupsApi(
        api_url=internal_groups_url,
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=client_secret,
    )
    api._client = requests.Session()  # type: ignore[assignment]
    return api


@pytest.fixture
def internal_groups_api(
    internal_groups_api_minimal: InternalGroupsApi,
    internal_groups_server_full_api_response: None,  # ruff: ignore[unused-function-argument]
) -> InternalGroupsApi:
    return internal_groups_api_minimal


@pytest.fixture
def internal_groups_client(
    internal_groups_url: str,
    issuer_url: str,
    client_id: str,
    client_secret: str,
    internal_groups_api: InternalGroupsApi,
) -> InternalGroupsClient:
    client = InternalGroupsClient(
        api_url=internal_groups_url,
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=client_secret,
    )
    client._api = internal_groups_api
    return client
