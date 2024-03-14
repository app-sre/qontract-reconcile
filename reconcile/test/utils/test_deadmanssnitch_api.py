import json

import httpretty
import pytest
from requests.exceptions import HTTPError

from reconcile.utils.deadmanssnitch_api import (
    DeadMansSnitchApi,
)

TOKEN = "test_token"
FAKE_URL = "https://fake.deadmanssnitch.com/v1/snitches"
@pytest.fixture
def deadmanssnitch_api() -> DeadMansSnitchApi:
    return DeadMansSnitchApi(token=TOKEN, url=FAKE_URL)


@httpretty.activate(allow_net_connect=False)
def test_get_all_snitches(deadmanssnitch_api: DeadMansSnitchApi) -> None:
    httpretty.register_uri(
        httpretty.GET,
        f"{deadmanssnitch_api.url}?tags=appsre",
        body=json.dumps([{
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
            "alert_email": ["test_mail"]
        }]),
        content_type="text/json",
        status=200,
    )
    snitches = deadmanssnitch_api.get_snitches(tags=["appsre"])
    assert len(snitches) == 1 and snitches[0].name == "test"


@httpretty.activate(allow_net_connect=False)
def test_get_all_snitches_failed(deadmanssnitch_api: DeadMansSnitchApi) -> None:
    httpretty.register_uri(
        httpretty.GET,
        f"{deadmanssnitch_api.url}?tags=appsre",
        body=json.dumps([{
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
            "alert_email": ["test_mail"]
        }]),
        content_type="text/json",
        status=401,
    )
    with pytest.raises(HTTPError):
        deadmanssnitch_api.get_snitches(tags=["appsre"])

@httpretty.activate(allow_net_connect=False)
def test_create_snitch(deadmanssnitch_api: DeadMansSnitchApi) -> None:
    httpretty.register_uri(
        httpretty.POST,
        deadmanssnitch_api.url,
        body=json.dumps({
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
            "alert_email": ["test_mail"]
        }),
        content_type="application/json",
        status=200,
    )
    snitch = deadmanssnitch_api.create_snitch(payload={"name": "test", "interval": "15_minute"})
    assert snitch.name == "test"


@httpretty.activate(allow_net_connect=False)
def test_create_snitch_failed(deadmanssnitch_api: DeadMansSnitchApi) -> None:
    httpretty.register_uri(
        httpretty.POST,
        deadmanssnitch_api.url,
        body=json.dumps({
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
            "alert_email": ["test_mail"]
        }),
        content_type="application/json",
        status=403,
    )
    with pytest.raises(HTTPError):
        deadmanssnitch_api.create_snitch(payload={"name": "test", "interval": "15_minute"})


@httpretty.activate(allow_net_connect=False)
def test_delete_snitch(deadmanssnitch_api: DeadMansSnitchApi) -> None:
    httpretty.register_uri(
        httpretty.DELETE,
        f"{deadmanssnitch_api.url}/{TOKEN}",
        status=200,
    )
    deadmanssnitch_api.delete_snitch(token=TOKEN)

@httpretty.activate(allow_net_connect=False)
def test_delete_snitch_failed(deadmanssnitch_api: DeadMansSnitchApi) -> None:
    httpretty.register_uri(
        httpretty.DELETE,
        f"{deadmanssnitch_api.url}/{TOKEN}",
        status=404,
    )
    with pytest.raises(HTTPError):
        deadmanssnitch_api.delete_snitch(token=TOKEN)
