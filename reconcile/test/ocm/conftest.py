import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import pytest
from pydantic.json import pydantic_encoder
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from reconcile.test.fixtures import Fixtures
from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm import OCM
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ocm")


@pytest.fixture
def access_token_url(httpserver: HTTPServer) -> str:
    return httpserver.url_for("/get_token")


@pytest.fixture
def ocm_url(httpserver: HTTPServer) -> str:
    return httpserver.url_for("/").rstrip("/")


@pytest.fixture(autouse=True)
def ocm_auth_mock(httpserver: HTTPServer, access_token_url: str) -> None:
    url = urlparse(access_token_url)
    httpserver.expect_request(url.path, method="post").respond_with_json({
        "access_token": "1234567890"
    })


@pytest.fixture
def ocm_api(
    access_token_url: str,
    ocm_url: str,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    clusters: list[dict[str, Any]],
    version_gates: list[dict[str, Any]],
) -> OCMBaseClient:
    register_ocm_url_responses([
        OcmUrl(method="GET", uri="/api/clusters_mgmt/v1/clusters").add_list_response(
            clusters
        ),
        OcmUrl(
            method="GET", uri="/api/clusters_mgmt/v1/version_gates"
        ).add_list_response(version_gates),
    ])
    return OCMBaseClient(
        access_token_client_id="some_client_id",
        access_token_client_secret="some_client_secret",
        access_token_url=access_token_url,
        url=ocm_url,
    )


@pytest.fixture
def register_ocm_url_responses(httpserver: HTTPServer) -> Callable[[list[OcmUrl]], int]:
    def f(urls: list[OcmUrl], max_page_size: int | None = None) -> int:
        i = 0
        for url in urls:
            i += len(url.responses) or 1
            if not url.responses:
                httpserver.expect_request(
                    url.uri, method=url.method
                ).respond_with_json({})
            else:
                for j, r in enumerate(url.responses):
                    query = None
                    if max_page_size is not None:
                        query = (
                            {"size": str(max_page_size)}
                            if j == 0
                            else {"page": str(j + 1), "size": str(max_page_size)}
                        )

                    httpserver.expect_request(
                        url.uri, method=url.method, query_string=query
                    ).respond_with_data(
                        json.dumps(r, default=pydantic_encoder),
                        content_type="text/json",
                    )
        return i

    return f


@pytest.fixture
def register_ocm_url_callback(
    httpserver: HTTPServer,
) -> Callable[[str, str, Callable], None]:
    def f(
        method: str,
        uri: str,
        callback: Callable[[Request], Response],
    ) -> None:
        httpserver.expect_request(uri, method=method).respond_with_handler(callback)

    return f


def _request_matches(
    req: Request, method: str, base_url: str, path: str | None = None
) -> bool:
    if req.method != method:
        return False

    parsed_url = urlparse(req.url)
    if f"{parsed_url.scheme}://{parsed_url.netloc}" != base_url:
        return False

    return not (path and parsed_url.path != path)


@pytest.fixture
def find_ocm_http_request(
    ocm_url: str, httpserver: HTTPServer, access_token_url: str
) -> Callable[[str, str], Request | None]:
    def find_request(method: str, path: str) -> Request | None:
        for req, _ in httpserver.log:
            if req.url == access_token_url:
                # ignore the access token request
                continue
            if _request_matches(req, method, ocm_url, path):
                return req

        return None

    return find_request


@pytest.fixture
def find_all_ocm_http_requests(
    ocm_url: str, httpserver: HTTPServer, access_token_url: str
) -> Callable[[str, str], list[Request]]:
    def find_request(method: str, path: str | None = None) -> list[Request]:
        matching_requests = []

        for req, _ in httpserver.log:
            if req.url == access_token_url:
                # ignore the access token request
                continue
            if _request_matches(req, method, ocm_url, path):
                matching_requests.append(req)

        return matching_requests

    return find_request


@pytest.fixture
def clusters() -> list[dict[str, Any]]:
    """
    Provides cluster fixtures for the `ocm_api` fixture.
    If a test module requires clusters, it can override this fixture
    fixture.
    """
    return []


@pytest.fixture
def version_gates() -> list[dict[str, Any]]:
    """
    Provides empty versiongate fixtures for the `ocm_api` fixture.
    If a test module requires versiongates, it can override this fixture
    """
    return []


@pytest.fixture
def ocm(
    ocm_api: OCMBaseClient,
) -> OCM:
    return OCM(
        "my-org",
        "org-id",
        "prod",
        ocm_api,
    )
