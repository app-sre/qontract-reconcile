import pytest
from pytest_httpserver import HTTPServer
from requests.exceptions import HTTPError

from reconcile.utils.deadmanssnitch_api import (
    DeadMansSnitchApi,
)

TOKEN = "test_token"
URL = "/v1/snitches"


@pytest.fixture
def deadmanssnitch_api(httpserver: HTTPServer) -> DeadMansSnitchApi:
    return DeadMansSnitchApi(token=TOKEN, url=httpserver.url_for(URL))


def test_get_all_snitches(
    httpserver: HTTPServer, deadmanssnitch_api: DeadMansSnitchApi
) -> None:
    httpserver.expect_request(URL, query_string="tags=appsre").respond_with_json([
        {
            "token": "test",
            "href": "testc",
            "name": "test",
            "tags": ["app-sre"],
            "notes": "test_notes",
            "status": "healthy",
            "check_in_url": "test_url",
            "type": {"interval": "15_minute"},
            "interval": "15_minute",
            "alert_type": "basic",
            "alert_email": ["test_mail"],
        }
    ])
    snitches = deadmanssnitch_api.get_snitches(tags=["appsre"])
    assert len(snitches) == 1 and snitches[0].name == "test"


def test_get_all_snitches_failed(
    httpserver: HTTPServer, deadmanssnitch_api: DeadMansSnitchApi
) -> None:
    httpserver.expect_request(URL, query_string="tags=appsre").respond_with_data(
        status=401
    )
    with pytest.raises(HTTPError):
        deadmanssnitch_api.get_snitches(tags=["appsre"])


def test_create_snitch(
    httpserver: HTTPServer, deadmanssnitch_api: DeadMansSnitchApi
) -> None:
    httpserver.expect_request(URL, method="POST").respond_with_json({
        "token": "test",
        "href": "testc",
        "name": "test",
        "tags": ["app-sre"],
        "notes": "test_notes",
        "status": "healthy",
        "check_in_url": "test_url",
        "type": {"interval": "15_minute"},
        "interval": "15_minute",
        "alert_type": "basic",
        "alert_email": ["test_mail"],
    })
    snitch = deadmanssnitch_api.create_snitch(
        payload={"name": "test", "interval": "15_minute"}
    )
    assert snitch.name == "test"


def test_create_snitch_failed(
    httpserver: HTTPServer, deadmanssnitch_api: DeadMansSnitchApi
) -> None:
    httpserver.expect_request(URL, method="POST").respond_with_data(status=403)
    with pytest.raises(HTTPError):
        deadmanssnitch_api.create_snitch(
            payload={"name": "test", "interval": "15_minute"}
        )


def test_delete_snitch(
    httpserver: HTTPServer, deadmanssnitch_api: DeadMansSnitchApi
) -> None:
    httpserver.expect_request(f"{URL}/{TOKEN}", method="DELETE").respond_with_data()
    deadmanssnitch_api.delete_snitch(token=TOKEN)


def test_delete_snitch_failed(
    httpserver: HTTPServer, deadmanssnitch_api: DeadMansSnitchApi
) -> None:
    httpserver.expect_request(f"{URL}/{TOKEN}", method="DELETE").respond_with_data(
        status=404
    )
    with pytest.raises(HTTPError):
        deadmanssnitch_api.delete_snitch(token=TOKEN)
