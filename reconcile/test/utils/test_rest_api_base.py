import json
from collections.abc import Generator, Mapping
from typing import Any

import httpretty as httpretty_module
import pytest

from reconcile.utils.rest_api_base import ApiBase, get_next_url


@pytest.fixture
def server_url() -> str:
    return "http://fake-server.com"


@pytest.fixture
def client(server_url: str) -> Generator[ApiBase, None, None]:
    client = ApiBase(host=server_url)
    yield client
    client.cleanup()


@pytest.mark.parametrize(
    "test_input, expected",
    [
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/?limit=1",
                    "rel": "previous",
                    "results": "false",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzEyJTNBMDElM0EwNS4xODYxNjElMkIwMCUzQTAw&limit=1",
                    "rel": "next",
                    "results": "true",
                    "cursor": "cD0yMDIyLTA5LTEzKzEyJTNBMDElM0EwNS4xODYxNjElMkIwMCUzQTAw",
                },
            },
            "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzEyJTNBMDElM0EwNS4xODYxNjElMkIwMCUzQTAw&limit=1",
        ),
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cj0xJnA9MjAyMi0wOS0xMysxMSUzQTIzJTNBMjMuMzA2MTQ4JTJCMDAlM0EwMA%3D%3D&limit=1",
                    "rel": "previous",
                    "results": "true",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw&limit=1",
                    "rel": "next",
                    "results": "true",
                    "cursor": "cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw",
                },
            },
            "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw&limit=1",
        ),
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cj0xJnA9MjAyMi0wOS0xMysxMCUzQTQxJTNBMjQuNDI3ODQxJTJCMDAlM0EwMA%3D%3D&limit=1",
                    "rel": "previous",
                    "results": "true",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw&limit=1",
                    "rel": "next",
                    "results": "false",
                },
            },
            None,
        ),
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/esa/teams/?limit=1",
                    "rel": "previous",
                    "results": "false",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/esa/teams/?limit=1",
                    "rel": "next",
                    "results": "false",
                },
            },
            None,
        ),
    ],
)
def test_get_next_url(
    test_input: dict[str, dict[str, str]], expected: str | None
) -> None:
    assert get_next_url(test_input) == expected


def test_glitchtip_client_list(
    httpretty: httpretty_module, client: ApiBase, server_url: str
) -> None:
    first_url = f"{server_url}/data"
    second_url = f"{server_url}/data2"

    httpretty.register_uri(
        httpretty.GET,
        first_url,
        body=json.dumps([1]),
        content_type="text/json",
        link=f"<{second_url}>; rel='next'; results='true'",
    )
    httpretty.register_uri(
        httpretty.GET,
        second_url,
        body=json.dumps([2]),
        content_type="text/json",
        link=f"<{second_url}>; rel='next'; results='false'",
    )
    assert client._list(first_url) == [1, 2]
    assert httpretty.last_request().headers


def test_glitchtip_client_get(
    httpretty: httpretty_module, client: ApiBase, server_url: str
) -> None:
    url = f"{server_url}/data"
    test_obj = {"test": "object"}
    httpretty.register_uri(
        httpretty.GET, url, body=json.dumps(test_obj), content_type="text/json"
    )
    assert client._get(url) == test_obj


def test_glitchtip_client_post(
    httpretty: httpretty_module, client: ApiBase, server_url: str
) -> None:
    url = f"{server_url}/data"
    request_data = {"test": "object"}
    response_data = {"foo": "bar"}

    def request_callback(
        request: httpretty_module.core.HTTPrettyRequest,
        uri: str,
        response_headers: Mapping[str, Any],
    ) -> tuple[int, Mapping[str, Any], str]:
        assert request.headers.get("Content-Type") == "application/json"
        assert json.loads(request.body) == request_data
        return (201, response_headers, json.dumps(response_data))

    httpretty.register_uri(
        httpretty.POST, url, content_type="text/json", body=request_callback
    )
    assert client._post(url, data=request_data) == response_data


def test_glitchtip_client_put(
    httpretty: httpretty_module, client: ApiBase, server_url: str
) -> None:
    url = f"{server_url}/data"
    request_data = {"test": "object"}
    response_data = {"foo": "bar"}

    def request_callback(
        request: httpretty_module.core.HTTPrettyRequest,
        uri: str,
        response_headers: Mapping[str, Any],
    ) -> tuple[int, Mapping[str, Any], str]:
        assert request.headers.get("Content-Type") == "application/json"
        assert json.loads(request.body) == request_data
        return (201, response_headers, json.dumps(response_data))

    httpretty.register_uri(
        httpretty.PUT, url, content_type="text/json", body=request_callback
    )
    assert client._put(url, data=request_data) == response_data


def test_glitchtip_client_delete(
    httpretty: httpretty_module, client: ApiBase, server_url: str
) -> None:
    url = f"{server_url}/data"
    httpretty.register_uri(httpretty.DELETE, url)
    client._delete(url)


def test_glitchtip_client_context_manager(
    httpretty: httpretty_module, server_url: str
) -> None:
    url = f"{server_url}/data"
    test_obj = {"test": "object"}
    httpretty.register_uri(
        httpretty.GET, url, body=json.dumps(test_obj), content_type="text/json"
    )
    with ApiBase(host=server_url) as client:
        assert client._get(url) == test_obj
