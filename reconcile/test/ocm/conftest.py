import json
from typing import (
    Callable,
    Optional,
)
from urllib.parse import urljoin

import httpretty as httpretty_module
import pytest
from httpretty.core import HTTPrettyRequest
from pydantic.json import pydantic_encoder

from reconcile.test.test_utils_ocm import OcmUrl
from reconcile.utils.ocm_base_client import OCMBaseClient


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
def find_http_request(
    httpretty: httpretty_module,
) -> Callable[[str, str], Optional[HTTPrettyRequest]]:
    def find_request(method: str, url: str) -> Optional[HTTPrettyRequest]:
        return next(
            (
                req
                for req in httpretty.latest_requests()
                if req.method == method and req.path == url
            ),
            None,
        )

    return find_request
