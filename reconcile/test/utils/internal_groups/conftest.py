from collections.abc import Callable

import pytest
import requests
from pytest_httpserver import HTTPServer

from reconcile.test.fixtures import Fixtures
from reconcile.utils.internal_groups.client import (
    InternalGroupsApi,
    InternalGroupsClient,
)


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("internal_groups")


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
def group_name() -> str:
    return "test-group"


@pytest.fixture
def non_existent_group_name() -> str:
    return "does-not-exist"


@pytest.fixture
def internal_groups_token() -> str:
    return "1234567890"


@pytest.fixture
def internal_groups_server_full_api_response(
    httpserver: HTTPServer,
    set_httpserver_responses_based_on_fixture: Callable,
    internal_groups_url: str,
    fx: Fixtures,
    group_name: str,
    non_existent_group_name: str,
) -> None:
    set_httpserver_responses_based_on_fixture(
        fx=fx,
        paths=["/v1/groups/", f"/v1/groups/{group_name}"],
    )
    # 404 for non-existent group
    for method in ["get", "put", "patch", "delete"]:
        httpserver.expect_request(
            f"/v1/groups/{non_existent_group_name}", method=method
        ).respond_with_data(status=404)


@pytest.fixture
def internal_groups_api_minimal(
    internal_groups_url: str, issuer_url: str, client_id: str, client_secret: str
) -> InternalGroupsApi:
    # ignore the OIDC token stuff for now. It's very hard to test
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
    internal_groups_server_full_api_response: None,
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
