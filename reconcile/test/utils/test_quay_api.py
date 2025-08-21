import json

import pytest
from pytest_httpserver import HTTPServer
from requests import HTTPError

from reconcile.utils.quay_api import (
    QuayApi,
    QuayTeamNotFoundError,
)

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


@responses.activate
def test_list_robot_accounts(quay_api: QuayApi) -> None:
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
def test_list_robot_accounts_raises_other_status_codes(quay_api: QuayApi) -> None:
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.list_robot_accounts()


@responses.activate
def test_create_robot_account(quay_api: QuayApi) -> None:
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        status=200,
        json={"name": "robot1", "description": "robot1 description"},
    )

    quay_api.create_robot_account("robot1", "robot1 description")

    assert responses.calls[0].request.body == b'{"description": "robot1 description"}'


@responses.activate
def test_create_robot_account_raises_other_status_codes(quay_api: QuayApi) -> None:
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.create_robot_account("robot1", "robot1 description")


@responses.activate
def test_delete_robot_account(quay_api: QuayApi) -> None:
    responses.add(
        responses.DELETE,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        status=200,
    )

    quay_api.delete_robot_account("robot1")
    assert responses.calls[0].request.method == "DELETE"
    assert (
        responses.calls[0].request.url
        == f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1"
    )


@responses.activate
def test_delete_robot_account_raises_other_status_codes(quay_api: QuayApi) -> None:
    responses.add(
        responses.DELETE,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.delete_robot_account("robot1")


@responses.activate
def test_get_repo_robot_permissions(quay_api: QuayApi) -> None:
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        status=200,
        json={"role": "write"},
    )

    result = quay_api.get_repo_robot_permissions("some-repo", "robot1")
    assert result == "write"


@responses.activate
def test_get_repo_robot_permissions_no_permission(quay_api: QuayApi) -> None:
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        status=400,
        json={"message": "User does not have permission for repo."},
    )

    result = quay_api.get_repo_robot_permissions("some-repo", "robot1")
    assert result is None


@responses.activate
def test_get_repo_robot_permissions_raises_other_status_codes(
    quay_api: QuayApi,
) -> None:
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        status=500,
    )

    with pytest.raises(HTTPError):
        quay_api.get_repo_robot_permissions("some-repo", "robot1")


@responses.activate
def test_set_repo_robot_permissions(quay_api: QuayApi) -> None:
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        status=200,
    )

    quay_api.set_repo_robot_permissions("some-repo", "robot1", "admin")

    assert responses.calls[0].request.body == b'{"role": "admin"}'


@responses.activate
def test_set_repo_robot_permissions_raises_other_status_codes(
    quay_api: QuayApi,
) -> None:
    responses.add(
        responses.PUT,
        f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.set_repo_robot_permissions("some-repo", "robot1", "admin")


@responses.activate
def test_delete_repo_robot_permissions(quay_api: QuayApi) -> None:
    responses.add(
        responses.DELETE,
        f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        status=200,
    )

    quay_api.delete_repo_robot_permissions("some-repo", "robot1")

    assert responses.calls[0].request.method == "DELETE"
    assert (
        responses.calls[0].request.url
        == f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1"
    )


@responses.activate
def test_delete_repo_robot_permissions_raises_other_status_codes(
    quay_api: QuayApi,
) -> None:
    responses.add(
        responses.DELETE,
        f"https://{BASE_URL}/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        status=400,
    )

    with pytest.raises(HTTPError):
        quay_api.delete_repo_robot_permissions("some-repo", "robot1")


@responses.activate
def test_get_robot_account_details_success(quay_api: QuayApi) -> None:
    robot_data = {"name": "test-robot", "description": "Test robot account"}
    permissions_data = {
        "permissions": [
            {"role": "team", "team": {"name": "test-team"}},
            {"role": "read", "repository": {"name": "test-repo"}},
        ]
    }

    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/test-robot",
        json=robot_data,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/test-robot/permissions",
        json=permissions_data,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/test-robot/permissions",
        json=permissions_data,
        status=200,
    )

    result = quay_api.get_robot_account_details("test-robot")

    assert result is not None
    assert result["name"] == "test-robot"
    assert result["description"] == "Test robot account"
    assert len(result["teams"]) == 1
    assert result["teams"][0]["name"] == "test-team"
    assert len(result["repositories"]) == 1
    assert result["repositories"][0]["name"] == "test-repo"
    assert result["repositories"][0]["role"] == "read"


@responses.activate
def test_get_robot_account_details_not_found(quay_api: QuayApi) -> None:
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/test-robot",
        status=404,
    )

    result = quay_api.get_robot_account_details("test-robot")
    assert result is None


@responses.activate
def test_list_robot_accounts_detailed(quay_api: QuayApi) -> None:
    robots_data = {"robots": [{"name": "robot1"}, {"name": "robot2"}]}
    robot1_details = {"name": "robot1", "description": "Robot 1"}
    robot2_details = {"name": "robot2", "description": "Robot 2"}
    permissions_data: dict[str, list[dict[str, str]]] = {"permissions": []}

    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots",
        json=robots_data,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1",
        json=robot1_details,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1/permissions",
        json=permissions_data,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot1/permissions",
        json=permissions_data,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot2",
        json=robot2_details,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot2/permissions",
        json=permissions_data,
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://{BASE_URL}/api/v1/organization/{ORG}/robots/robot2/permissions",
        json=permissions_data,
        status=200,
    )

    result = quay_api.list_robot_accounts_detailed()

    assert len(result) == 2
    assert result[0]["name"] == "robot1"
    assert result[1]["name"] == "robot2"
