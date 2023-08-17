from collections.abc import Callable

import httpretty as httpretty_module
import pytest
import requests

from reconcile.test.fixtures import Fixtures
from reconcile.utils.internal_groups.client import (
    InternalGroupsApi,
    InternalGroupsClient,
)


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("internal_groups")


@pytest.fixture
def internal_groups_url() -> str:
    return "http://fake-internal-groups-server.com"


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
    httpretty: httpretty_module,
    set_httpretty_responses_based_on_fixture: Callable,
    internal_groups_url: str,
    fx: Fixtures,
    group_name: str,
    non_existent_group_name: str,
) -> None:
    set_httpretty_responses_based_on_fixture(
        url=internal_groups_url,
        fx=fx,
        paths=["v1/groups/", f"v1/groups/{group_name}"],
    )
    # 404 for non-existent group
    for method in ["get", "put", "patch", "delete"]:
        httpretty.register_uri(
            getattr(httpretty, method.upper()),
            f"{internal_groups_url}/v1/groups/{non_existent_group_name}",
            status=404,
        )


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
    api._client = requests.Session()
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
