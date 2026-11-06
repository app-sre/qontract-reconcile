"""Unit tests for ldap-groups router."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.ldap_groups.schemas import LdapGroupsTaskResult
from qontract_api.models import TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK

ENDPOINT = "/api/v1/integrations/ldap-groups/reconcile"


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_request() -> dict:
    return {
        "connection": {
            "secret_manager_url": "https://vault.example.com",
            "path": "creds",
            "api_url": "https://groups.example.com",
            "issuer_url": "https://sso.example.com",
            "client_id": "client-id",
        },
        "desired_groups": [
            {
                "name": "group-a",
                "description": "desc",
                "contactList": "a@example.com",
                "owners": [{"type": "serviceaccount", "id": "sa-1"}],
                "displayName": "group-a",
                "members": [{"type": "user", "id": "user-1"}],
            }
        ],
        "managed_group_names": [],
        "dry_run": True,
    }


@patch("qontract_api.integrations.ldap_groups.router.reconcile_ldap_groups_task")
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_request: dict,
) -> None:
    response = client.post(ENDPOINT, json=sample_request, headers=auth_headers)
    assert response.status_code == HTTPStatus.ACCEPTED
    request_id = response.headers[REQUEST_ID_HEADER]
    assert response.json()["id"] == request_id
    mock_task.apply_async.assert_called_once()
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_MR_CHECK


@patch("qontract_api.integrations.ldap_groups.router.wait_for_task_completion")
def test_get_task_status(
    mock_wait: MagicMock, client: TestClient, auth_headers: dict[str, str]
) -> None:
    mock_wait.return_value = LdapGroupsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        errors=[],
        updated_managed_groups=[],
    )
    response = client.get(f"{ENDPOINT}/task-1", headers=auth_headers)
    assert response.status_code == HTTPStatus.OK
