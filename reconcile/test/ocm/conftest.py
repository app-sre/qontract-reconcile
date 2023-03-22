import json
from typing import (
    Any,
    Optional,
)

import httpretty as httpretty_module
import pytest
from pydantic.json import pydantic_encoder

from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def access_token_url() -> str:
    return "https://sso/get_token"


@pytest.fixture
def ocm_auth_mock(httpretty: httpretty_module, access_token_url: str) -> None:
    httpretty.register_uri(
        httpretty.POST,
        access_token_url,
        body=json.dumps({"access_token": "1234567890"}),
        content_type="text/json",
    )


@pytest.fixture
def ocm_api(
    ocm_auth_mock: None, httpretty: httpretty_module, access_token_url: str
) -> OCMBaseClient:
    return OCMBaseClient(
        access_token_client_id="some_client_id",
        access_token_client_secret="some_client_secret",
        access_token_url=access_token_url,
        url="http://ocm",
    )


def register_ocm_get_list_request(
    ocm_api: OCMBaseClient, httpretty: httpretty_module, url: str, result: list[Any]
) -> None:
    httpretty.register_uri(
        httpretty.GET,
        f"{ocm_api._url}{url}",
        body=json.dumps({"items": result}, default=pydantic_encoder),
        content_type="text/json",
    )


def register_ocm_post_request(
    ocm_api: OCMBaseClient,
    httpretty: httpretty_module,
    url: str,
    result: Optional[Any] = None,
) -> None:
    httpretty.register_uri(
        httpretty.POST,
        f"{ocm_api._url}{url}",
        body=json.dumps(result, default=pydantic_encoder) if result else "{}",
        content_type="text/json",
    )


def register_ocm_delete_request(
    ocm_api: OCMBaseClient,
    httpretty: httpretty_module,
    url: str,
    result: Optional[Any] = None,
) -> None:
    httpretty.register_uri(
        httpretty.DELETE,
        f"{ocm_api._url}{url}",
        body=json.dumps(result, default=pydantic_encoder) if result else "{}",
        content_type="text/json",
    )
