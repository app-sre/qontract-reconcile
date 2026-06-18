from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from reconcile.test.fixtures import Fixtures
from reconcile.utils.unleash.server import UnleashServer

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_httpserver import HTTPServer


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
            "/" + p.relative_to(fx.path("")).as_posix()
            for p in Path(fx.path("")).rglob("*")
            if p.is_dir()
        ],
    )
