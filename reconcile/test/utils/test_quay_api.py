import json

import pytest
import responses
from requests import HTTPError

from reconcile.utils.quay_api import (
    QuayApi,
    QuayTeamNotFoundError,
)

ORG = "some-org"
BASE_URL = "some.quay.io"
TEAM_NAME = "some-team"


@pytest.fixture
def quay_api() -> QuayApi:
    return QuayApi("some-token", ORG, base_url=BASE_URL)


@responses.activate
def test_create_or_update_team_default_payload(quay_api: QuayApi) -> None:
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/team/{TEAM_NAME}",
        status=200,
    )

    quay_api.create_or_update_team(TEAM_NAME)

    assert responses.calls[0].request.body is not None
    assert json.loads(responses.calls[0].request.body) == {"role": "member"}


@responses.activate
def test_create_or_update_team_with_description(quay_api: QuayApi) -> None:
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/team/{TEAM_NAME}",
        status=200,
    )

    quay_api.create_or_update_team(TEAM_NAME, description="This is a team")

    assert responses.calls[0].request.body is not None
    assert json.loads(responses.calls[0].request.body) == {
        "role": "member",
        "description": "This is a team",
    }


@responses.activate
def test_create_or_update_team_raises(quay_api: QuayApi) -> None:
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/team/{TEAM_NAME}",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.create_or_update_team(TEAM_NAME)


@responses.activate
def test_list_team_members_raises_team_doesnt_exist(quay_api: QuayApi) -> None:
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/team/{TEAM_NAME}/"
        f"members?includePending=true",
        status=404,
    )

    with pytest.raises(QuayTeamNotFoundError):
        quay_api.list_team_members(TEAM_NAME)


@responses.activate
def test_list_team_members_raises_other_status_codes(quay_api: QuayApi) -> None:
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/team/{TEAM_NAME}/"
        f"members?includePending=true",
        status=401,
    )

    with pytest.raises(HTTPError):
        quay_api.list_team_members(TEAM_NAME)


@responses.activate
def test_list_robot_accounts(quay_api):
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots",
        status=200,
        json={
            "robots": [
                {
                    "name": "robot1",
                    "description": "robot1 description",
                    "created": "2021-01-01T00:00:00Z",
                    "last_accessed": None,
                },
                {
                    "name": "robot2",
                    "description": "robot2 description",
                    "created": "2021-01-01T00:00:00Z",
                    "last_accessed": None,
                },
            ]
        },
    )

    assert quay_api.list_robot_accounts() == [
        {
            "name": "robot1",
            "description": "robot1 description",
            "created": "2021-01-01T00:00:00Z",
            "last_accessed": None,
        },
        {
            "name": "robot2",
            "description": "robot2 description",
            "created": "2021-01-01T00:00:00Z",
            "last_accessed": None,
        },
    ]

@responses.activate
def test_list_robot_accounts_raises_other_status_codes(quay_api):
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.list_robot_accounts()

@responses.activate
def test_create_robot_account(quay_api):
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        status=200,
        json={"name": "robot1", "description": "robot1 description"},
    )

    quay_api.create_robot_account("robot1", "robot1 description")

    assert responses.calls[0].request.body == b'{"description": "robot1 description"}'

@responses.activate
def test_create_robot_account_raises_other_status_codes(quay_api):
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.create_robot_account("robot1", "robot1 description")

@responses.activate
def test_delete_robot_account(quay_api):
    responses.add(
        responses.DELETE,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        status=200,
    )

    quay_api.delete_robot_account("robot1")
    assert responses.calls[0].request.method == "DELETE"
    assert responses.calls[0].request.url == f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1"

