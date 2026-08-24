"""Tests for qontract_utils.quay_api.QuayApi."""

from unittest.mock import MagicMock, patch

import httpx2
import pytest
from qontract_utils.quay_api import QuayApi
from qontract_utils.quay_api.client import _normalize_host

ORG = "some-org"


@pytest.fixture
def mock_httpx_client() -> MagicMock:
    return MagicMock(spec=httpx2.Client)


@pytest.fixture
def quay_api(mock_httpx_client: MagicMock) -> QuayApi:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        mock_cls.return_value = mock_httpx_client
        return QuayApi(token="some-token", organization=ORG, base_url="quay.io")


def _response(
    status: int = 200,
    json_body: dict | list | None = None,
    content: bytes | None = None,
) -> httpx2.Response:
    request = httpx2.Request("GET", "https://quay.io/")
    if json_body is not None:
        return httpx2.Response(status, json=json_body, request=request)
    if content is not None:
        return httpx2.Response(status, content=content, request=request)
    return httpx2.Response(status, request=request)


def test_normalize_host_hostname() -> None:
    assert _normalize_host("quay.io") == "https://quay.io"


def test_normalize_host_full_url() -> None:
    assert _normalize_host("http://localhost:12345/") == "http://localhost:12345"


def test_quay_api_default_user_agent() -> None:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        QuayApi(token="token", organization=ORG)
    headers = mock_cls.call_args.kwargs["headers"]
    assert headers["User-Agent"].startswith("qontract-utils/")
    assert headers["Authorization"] == "Bearer token"


def test_list_robot_accounts(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.get.return_value = _response(
        json_body={
            "robots": [
                {
                    "name": f"{ORG}+robot1",
                    "description": "robot1 description",
                    "teams": [{"name": "team1"}, {"name": "team2"}],
                    "repositories": ["repo1"],
                },
                {
                    "name": f"{ORG}+robot2",
                    "description": "robot2 description",
                    "teams": [],
                    "repositories": [],
                },
            ]
        }
    )

    robots = quay_api.list_robot_accounts()

    assert [r.name for r in robots] == ["robot1", "robot2"]
    assert robots[0].teams == ["team1", "team2"]
    assert robots[0].repositories == ["repo1"]
    mock_httpx_client.get.assert_called_once_with(
        f"/api/v1/organization/{ORG}/robots",
        params={"permissions": "true"},
    )


def test_list_robot_accounts_http_error(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.get.return_value = _response(
        400, json_body={"error": "Bad request"}
    )
    with pytest.raises(httpx2.HTTPStatusError):
        quay_api.list_robot_accounts()


def test_create_robot_account(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.put.return_value = _response(
        json_body={"name": "robot1", "description": "robot1 description"}
    )

    quay_api.create_robot_account("robot1", "robot1 description")

    mock_httpx_client.put.assert_called_once_with(
        f"/api/v1/organization/{ORG}/robots/robot1",
        json={"description": "robot1 description"},
    )


def test_delete_robot_account(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.delete.return_value = _response()
    quay_api.delete_robot_account("robot1")
    mock_httpx_client.delete.assert_called_once_with(
        f"/api/v1/organization/{ORG}/robots/robot1"
    )


def test_delete_robot_account_http_error(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.delete.return_value = _response(400, json_body={"error": "Bad"})
    with pytest.raises(httpx2.HTTPStatusError):
        quay_api.delete_robot_account("robot1")


def test_get_robot_account_permissions(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.get.return_value = _response(
        json_body={
            "permissions": [
                {"repository": {"name": "repo1"}, "role": "read"},
                {"repository": {"name": "repo2"}, "role": "write"},
            ]
        }
    )

    perms = quay_api.get_robot_account_permissions("robot1")

    assert len(perms) == 2
    assert perms[0].repository.name == "repo1"
    assert perms[0].role == "read"
    mock_httpx_client.get.assert_called_once_with(
        f"/api/v1/organization/{ORG}/robots/robot1/permissions",
        params=None,
    )


def test_get_robot_account_permissions_http_error(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.get.return_value = _response(
        401, json_body={"error": "Unauthorized"}
    )
    with pytest.raises(httpx2.HTTPStatusError):
        quay_api.get_robot_account_permissions("robot1")


def test_add_user_to_team(quay_api: QuayApi, mock_httpx_client: MagicMock) -> None:
    mock_httpx_client.put.return_value = _response(204, content=b"")
    quay_api.add_user_to_team(f"{ORG}+robot1", "some-team")
    mock_httpx_client.put.assert_called_once_with(
        f"/api/v1/organization/{ORG}/team/some-team/members/{ORG}+robot1"
    )


def test_remove_robot_from_team(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.delete.return_value = _response(204, content=b"")
    quay_api.remove_robot_from_team("robot1", "some-team")
    mock_httpx_client.delete.assert_called_once_with(
        f"/api/v1/organization/{ORG}/team/some-team/members/{ORG}+robot1"
    )


def test_remove_robot_from_team_idempotent_when_not_in_team(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.delete.return_value = _response(
        400,
        json_body={"message": f"User {ORG}+robot1 does not belong to team some-team"},
    )
    quay_api.remove_robot_from_team("robot1", "some-team")


def test_remove_robot_from_team_raises_other_errors(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.delete.return_value = _response(
        401, json_body={"error": "Unauthorized"}
    )
    with pytest.raises(httpx2.HTTPStatusError):
        quay_api.remove_robot_from_team("robot1", "some-team")


def test_set_repo_robot_account_permissions(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.put.return_value = _response(json_body={})
    quay_api.set_repo_robot_account_permissions("some-repo", "robot1", "admin")
    mock_httpx_client.put.assert_called_once_with(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1",
        json={"role": "admin"},
    )


def test_set_repo_robot_account_permissions_http_error(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.put.return_value = _response(400, json_body={"error": "Bad"})
    with pytest.raises(httpx2.HTTPStatusError):
        quay_api.set_repo_robot_account_permissions("some-repo", "robot1", "admin")


def test_delete_repo_robot_account_permissions(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.delete.return_value = _response()
    quay_api.delete_repo_robot_account_permissions("some-repo", "robot1")
    mock_httpx_client.delete.assert_called_once_with(
        f"/api/v1/repository/{ORG}/some-repo/permissions/user/{ORG}+robot1"
    )


def test_delete_repo_robot_account_permissions_http_error(
    quay_api: QuayApi, mock_httpx_client: MagicMock
) -> None:
    mock_httpx_client.delete.return_value = _response(400, json_body={"error": "Bad"})
    with pytest.raises(httpx2.HTTPStatusError):
        quay_api.delete_repo_robot_account_permissions("some-repo", "robot1")


def test_context_manager_closes_client(mock_httpx_client: MagicMock) -> None:
    with patch("qontract_utils.quay_api.client.httpx2.Client") as mock_cls:
        mock_cls.return_value = mock_httpx_client
        with QuayApi(token="t", organization=ORG) as api:
            assert api.organization == ORG
    mock_httpx_client.close.assert_called_once()
