import json
from typing import Optional

import pytest
from reconcile.utils.glitchtip.client import get_next_url, GlitchtipClient
import httpretty as httpretty_module


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
    test_input: dict[str, dict[str, str]], expected: Optional[str]
) -> None:
    assert get_next_url(test_input) == expected


@pytest.fixture
def glitchtip_url() -> str:
    return "http://fake-glitchtip-server.com"


@pytest.fixture
def glitchtip_token() -> str:
    return "1234567890"


@pytest.fixture
def glitchtip_client(glitchtip_url, glitchtip_token) -> GlitchtipClient:
    return GlitchtipClient(host=glitchtip_url, token=glitchtip_token)


def test_glitchtip_client_list(
    httpretty: httpretty_module,
    glitchtip_client: GlitchtipClient,
    glitchtip_url: str,
    glitchtip_token: str,
):
    first_url = f"{glitchtip_url}/data"
    second_url = f"{glitchtip_url}/data2"

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
    assert glitchtip_client._list(first_url) == [1, 2]
    assert httpretty.last_request().headers


def test_glitchtip_client_get(
    httpretty: httpretty_module,
    glitchtip_client: GlitchtipClient,
    glitchtip_url: str,
    glitchtip_token: str,
):
    url = f"{glitchtip_url}/data"
    test_obj = {"test": "object"}
    httpretty.register_uri(
        httpretty.GET, url, body=json.dumps(test_obj), content_type="text/json"
    )
    assert glitchtip_client._get(url) == test_obj
