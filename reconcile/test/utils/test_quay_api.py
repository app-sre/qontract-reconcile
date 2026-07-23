from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from requests import HTTPError

from reconcile.utils.quay_api import (
    QuayApi,
    QuayTeamNotFoundError,
)

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer

ORG = "some-org"
TEAM_NAME = "some-team"


@pytest.fixture
def quay_url(httpserver: HTTPServer) -> str:
    return httpserver.url_for("")


@pytest.fixture
def quay_api(quay_url: str) -> QuayApi:
    return QuayApi("some-token", ORG, base_url=quay_url)


def test_create_or_update_team_default_payload(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/team/{TEAM_NAME}",
        method="PUT",
    ).respond_with_json({}, status=200)

    quay_api.create_or_update_team(TEAM_NAME)

    assert len(httpserver.log) == 1
    request = httpserver.log[0][0]
    assert request.method == "PUT"
    assert json.loads(request.get_data()) == {"role": "member"}


def test_create_or_update_team_with_description(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/team/{TEAM_NAME}",
        method="PUT",
    ).respond_with_json({}, status=200)

    quay_api.create_or_update_team(TEAM_NAME, description="This is a team")

    assert len(httpserver.log) == 1
    request = httpserver.log[0][0]
    assert request.method == "PUT"
    assert json.loads(request.get_data()) == {
        "role": "member",
        "description": "This is a team",
    }


def test_create_or_update_team_raises(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/team/{TEAM_NAME}",
        method="PUT",
    ).respond_with_json({"error": "Bad request"}, status=400)

    with pytest.raises(HTTPError):
        quay_api.create_or_update_team(TEAM_NAME)


def test_list_team_members_raises_team_doesnt_exist(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/team/{TEAM_NAME}/members",
        method="GET",
        query_string="includePending=true",
    ).respond_with_json({"error": "Not found"}, status=404)

    with pytest.raises(QuayTeamNotFoundError):
        quay_api.list_team_members(TEAM_NAME)


def test_list_team_members_raises_other_status_codes(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/team/{TEAM_NAME}/members",
        method="GET",
        query_string="includePending=true",
    ).respond_with_json({"error": "Unauthorized"}, status=401)

    with pytest.raises(HTTPError):
        quay_api.list_team_members(TEAM_NAME)


def test_list_robot_accounts(quay_api: QuayApi, httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/robots",
        method="GET",
        query_string="permissions=true",
    ).respond_with_json(
        {
            "robots": [
                {
                    "name": f"{ORG}+robot1",
                    "description": "robot1 description",
                    "created": "2021-01-01T00:00:00Z",
                    "last_accessed": None,
                    "teams": [{"name": "team1"}, {"name": "team2"}],
                    "repositories": ["repo1"],
                },
                {
                    "name": f"{ORG}+robot2",
                    "description": "robot2 description",
                    "created": "2021-01-01T00:00:00Z",
                    "last_accessed": None,
                    "teams": [],
                    "repositories": [],
                },
            ]
        },
        status=200,
    )

    assert quay_api.list_robot_accounts() == [
        {
            "name": "robot1",
            "description": "robot1 description",
            "teams": [{"name": "team1"}, {"name": "team2"}],
            "repositories": ["repo1"],
        },
        {
            "name": "robot2",
            "description": "robot2 description",
            "teams": [],
            "repositories": [],
        },
    ]


def test_list_robot_accounts_raises_other_status_codes(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/robots",
        method="GET",
    ).respond_with_json({"error": "Bad request"}, status=400)

    with pytest.raises(HTTPError):
        quay_api.list_robot_accounts()


def test_create_robot_account(quay_api: QuayApi, httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/robots/robot1",
        method="PUT",
    ).respond_with_json(
        {"name": "robot1", "description": "robot1 description"}, status=200
    )

    quay_api.create_robot_account("robot1", "robot1 description")

    assert len(httpserver.log) == 1
    request = httpserver.log[0][0]
    assert request.method == "PUT"
    assert json.loads(request.get_data()) == {"description": "robot1 description"}


def test_delete_robot_account(quay_api: QuayApi, httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/robots/robot1",
        method="DELETE",
    ).respond_with_json({}, status=200)

    quay_api.delete_robot_account("robot1")

    assert len(httpserver.log) == 1
    request = httpserver.log[0][0]
    assert request.method == "DELETE"


def test_delete_robot_account_raises_other_status_codes(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/organization/{ORG}/robots/robot1",
        method="DELETE",
    ).respond_with_json({"error": "Bad request"}, status=400)

    with pytest.raises(HTTPError):
        quay_api.delete_robot_account("robot1")


def test_get_repo_robot_account_permissions(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        method="GET",
    ).respond_with_json({"role": "write"}, status=200)

    result = quay_api.get_repo_robot_account_permissions("some-repo", "robot1")
    assert result == "write"


def test_get_repo_robot_account_permissions_returns_none_when_no_permission(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        method="GET",
    ).respond_with_json(
        {"message": "User does not have permission for repo."}, status=404
    )

    result = quay_api.get_repo_robot_account_permissions("some-repo", "robot1")
    assert result is None


def test_get_repo_robot_permissions_raises_other_status_codes(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        method="GET",
    ).respond_with_json({"error": "Bad request"}, status=400)

    with pytest.raises(HTTPError):
        quay_api.get_repo_robot_account_permissions("some-repo", "robot1")


def test_set_repo_robot_permissions(quay_api: QuayApi, httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        method="PUT",
    ).respond_with_json({}, status=200)

    quay_api.set_repo_robot_account_permissions("some-repo", "robot1", "admin")

    assert len(httpserver.log) == 1
    request = httpserver.log[0][0]
    assert request.method == "PUT"
    assert json.loads(request.get_data()) == {"role": "admin"}


def test_set_repo_robot_permissions_raises_other_status_codes(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        method="PUT",
    ).respond_with_json({"error": "Bad request"}, status=400)

    with pytest.raises(HTTPError):
        quay_api.set_repo_robot_account_permissions("some-repo", "robot1", "admin")


def test_delete_repo_robot_permissions(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        method="DELETE",
    ).respond_with_json({}, status=200)

    quay_api.delete_repo_robot_account_permissions("some-repo", "robot1")

    assert len(httpserver.log) == 1
    request = httpserver.log[0][0]
    assert request.method == "DELETE"


def test_delete_repo_robot_permissions_raises_other_status_codes(
    quay_api: QuayApi, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        method="DELETE",
    ).respond_with_json({"error": "Bad request"}, status=400)

    with pytest.raises(HTTPError):
        quay_api.delete_repo_robot_account_permissions("some-repo", "robot1")
