import json
from collections.abc import Callable
from typing import (
    Any,
    Optional,
)
from urllib.parse import (
    urljoin,
    urlparse,
)

import httpretty as httpretty_module
import pytest
from httpretty.core import HTTPrettyRequest
from pydantic.json import pydantic_encoder

from reconcile.test.fixtures import Fixtures
from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm.ocm import OCM
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ocm")


@pytest.fixture
def access_token_url() -> str:
    return "https://sso/get_token"


@pytest.fixture
def ocm_url() -> str:
    return "http://ocm"


@pytest.fixture
def ocm_auth_mock(httpretty: httpretty_module, access_token_url: str) -> None:
    httpretty.register_uri(
        httpretty.POST,
        access_token_url,
        body=json.dumps({"access_token": "1234567890"}),
        content_type="text/json",
    )


@pytest.fixture
def ocm_api(ocm_auth_mock: None, access_token_url: str, ocm_url: str) -> OCMBaseClient:
    return OCMBaseClient(
        access_token_client_id="some_client_id",
        access_token_client_secret="some_client_secret",
        access_token_url=access_token_url,
        url=ocm_url,
    )


@pytest.fixture
def register_ocm_url_responses(
    ocm_url: str, httpretty: httpretty_module
) -> Callable[[list[OcmUrl]], int]:
    def f(urls: list[OcmUrl]) -> int:
        i = 0
        for url in urls:
            i += len(url.responses) or 1
            httpretty.register_uri(
                url.method.upper(),
                urljoin(ocm_url, url.uri),
                responses=[
                    httpretty.Response(body=json.dumps(r, default=pydantic_encoder))
                    for r in url.responses
                ],
                content_type="text/json",
            )
        return i

    return f


@pytest.fixture
def register_ocm_url_callback(
    ocm_url: str, httpretty: httpretty_module
) -> Callable[[str, str, Callable], None]:
    def f(
        method: str,
        uri: str,
        callback: Callable[
            [HTTPrettyRequest, str, dict[str, str]], tuple[int, dict, str]
        ],
    ) -> None:
        httpretty.register_uri(
            method.upper(),
            urljoin(ocm_url, uri),
            body=callback,
            content_type="text/json",
        )

    return f


@pytest.fixture
def find_ocm_http_request(
    ocm_url: str,
    httpretty: httpretty_module,
) -> Callable[[str, str], Optional[HTTPrettyRequest]]:
    def find_request(method: str, path: str) -> Optional[HTTPrettyRequest]:
        for req in httpretty.latest_requests():
            if req.method != method:
                continue

            parsed_url = urlparse(req.url)
            if f"{parsed_url.scheme}://{parsed_url.netloc}" != ocm_url:
                continue

            if parsed_url.path != path:
                continue

            return req

        return None

    return find_request


@pytest.fixture
def clusters() -> list[dict[str, Any]]:
    """
    Provides cluster fixtures for the `ocm` fixture.
    If a test module required actual clusters, it can override the `clusters`
    fixture.
    """
    return []


@pytest.fixture
def ocm(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    clusters: list[dict[str, Any]],
) -> OCM:
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET", uri="/api/clusters_mgmt/v1/clusters"
            ).add_list_response(clusters)
        ]
    )
    return OCM(
        "my-org",
        "org-id",
        ocm_api,
    )
