from collections.abc import Generator

import pytest
from pytest_httpserver import HTTPServer
from requests import HTTPError

from reconcile.utils.rest_api_base import ApiBase, BearerTokenAuth, get_next_url


@pytest.fixture
def client(httpserver: HTTPServer) -> Generator[ApiBase, None, None]:
    client = ApiBase(host=httpserver.url_for("/"))
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


def test_rest_api_base_client_list(httpserver: HTTPServer, client: ApiBase) -> None:
    first_url = "/data"
    second_url = "/data2"

    httpserver.expect_request(first_url).respond_with_json(
        [1],
        headers={
            "Link": f"<{httpserver.url_for(second_url)}>; rel='next'; results='true'"
        },
    )

    httpserver.expect_request(second_url).respond_with_json(
        [2],
        headers={
            "Link": f"<{httpserver.url_for(second_url)}>; rel='next'; results='false'"
        },
    )

    assert client._list(first_url) == [1, 2]


def test_rest_api_base_client_list_500(client: ApiBase) -> None:
    with pytest.raises(HTTPError):
        assert client._list("/data")


def test_rest_api_base_client_get(httpserver: HTTPServer, client: ApiBase) -> None:
    url = "/data"
    test_obj = {"test": "object"}
    httpserver.expect_request(url).respond_with_json(test_obj)
    assert client._get(url) == test_obj


def test_rest_api_base_client_get_500(client: ApiBase) -> None:
    with pytest.raises(HTTPError):
        assert client._get("/data")


def test_rest_api_base_client_post(httpserver: HTTPServer, client: ApiBase) -> None:
    url = "/data"
    request_data = {"test": "object"}
    response_data = {"foo": "bar"}

    httpserver.expect_request(
        url,
        method="post",
        headers={"Content-Type": "application/json"},
        json=request_data,
    ).respond_with_json(response_data)
    assert client._post(url, data=request_data) == response_data


def test_rest_api_base_client_post_204(httpserver: HTTPServer, client: ApiBase) -> None:
    url = "/data"
    request_data = {"test": "object"}

    httpserver.expect_request(
        url,
        method="post",
        headers={"Content-Type": "application/json"},
        json=request_data,
    ).respond_with_data(status=204)
    assert client._post(url, data=request_data) == {}


def test_rest_api_base_client_post_500(client: ApiBase) -> None:
    with pytest.raises(HTTPError):
        assert client._post("/data", data={})


def test_rest_api_base_client_put(httpserver: HTTPServer, client: ApiBase) -> None:
    url = "/data"
    request_data = {"test": "object"}
    response_data = {"foo": "bar"}

    httpserver.expect_request(
        url,
        method="put",
        headers={"Content-Type": "application/json"},
        json=request_data,
    ).respond_with_json(response_data)
    assert client._put(url, data=request_data) == response_data


def test_rest_api_base_client_put_204(httpserver: HTTPServer, client: ApiBase) -> None:
    url = "/data"
    request_data = {"test": "object"}

    httpserver.expect_request(
        url,
        method="put",
        headers={"Content-Type": "application/json"},
        json=request_data,
    ).respond_with_data(status=204)
    assert client._put(url, data=request_data) == {}


def test_rest_api_base_client_put_500(client: ApiBase) -> None:
    with pytest.raises(HTTPError):
        assert client._put("/data", data={})


def test_rest_api_base_client_delete(httpserver: HTTPServer, client: ApiBase) -> None:
    url = "/data"
    httpserver.expect_request(url, method="delete").respond_with_data()
    client._delete(url)


def test_rest_api_base_client_delete_500(client: ApiBase) -> None:
    with pytest.raises(HTTPError):
        client._delete("/data")


def test_rest_api_base_client_context_manager(httpserver: HTTPServer) -> None:
    url = "/data"
    test_obj = {"test": "object"}
    httpserver.expect_request(url).respond_with_json(test_obj)
    with ApiBase(host=httpserver.url_for("/")) as client:
        assert client._get(url) == test_obj


def test_rest_api_base_client_bearer_auth(httpserver: HTTPServer) -> None:
    url = "/data"
    test_obj = {"test": "object"}
    httpserver.expect_request(
        url, headers={"Authorization": "Bearer token"}
    ).respond_with_json(test_obj)
    with ApiBase(host=httpserver.url_for("/"), auth=BearerTokenAuth("token")) as client:
        assert client._get(url) == test_obj
