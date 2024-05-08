from collections.abc import Callable

import pytest
from pytest_httpserver import HTTPServer

from reconcile.test.fixtures import Fixtures
from reconcile.utils.unleash.server import UnleashServer


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("unleash")


@pytest.fixture
def unleash_server_url(httpserver: HTTPServer) -> str:
    return httpserver.url_for("")


@pytest.fixture
def client_minimal(unleash_server_url: str) -> UnleashServer:
    return UnleashServer(host=unleash_server_url)


@pytest.fixture
def client(
    client_minimal: UnleashServer, unleash_server_full_api_response: None
) -> UnleashServer:
    return client_minimal


@pytest.fixture
def unleash_server_full_api_response(
    set_httpserver_responses_based_on_fixture: Callable,
    fx: Fixtures,
) -> None:
    set_httpserver_responses_based_on_fixture(
        fx=fx,
        paths=[
            "/api/admin/projects",
        ],
    )
