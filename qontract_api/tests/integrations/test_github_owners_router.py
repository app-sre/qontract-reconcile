"""Unit tests for github-owners router endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.github_owners.domain import GithubOrgDesiredState
from qontract_api.integrations.github_owners.schemas import (
    GithubOwnersReconcileRequest,
    GithubOwnersTaskResult,
)
from qontract_api.models import Secret, TaskStatus, TokenData


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_org() -> GithubOrgDesiredState:
    return GithubOrgDesiredState(
        org_name="my-org",
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path="secret/github/token",
        ),
        owners=["alice", "bob"],
    )


@pytest.fixture
def sample_reconcile_request(
    sample_org: GithubOrgDesiredState,
) -> GithubOwnersReconcileRequest:
    return GithubOwnersReconcileRequest(
        organizations=[sample_org],
        dry_run=True,
    )


@patch("qontract_api.integrations.github_owners.router.reconcile_github_owners_task")
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: GithubOwnersReconcileRequest,
) -> None:
    """POST /reconcile queues Celery task and returns task ID."""
    response = client.post(
        "/api/v1/integrations/github-owners/reconcile",
        json=sample_reconcile_request.model_dump(),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert data["id"] == request_id
    assert data["status"] == TaskStatus.PENDING.value
    assert f"/reconcile/{request_id}" in data["status_url"]

    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is True
    assert len(call_kwargs["organizations"]) == 1


@patch("qontract_api.integrations.github_owners.router.reconcile_github_owners_task")
def test_post_reconcile_dry_run_false(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_org: GithubOrgDesiredState,
) -> None:
    """POST /reconcile passes dry_run=False to the task."""
    request_data = {
        "organizations": [sample_org.model_dump()],
        "dry_run": False,
    }

    response = client.post(
        "/api/v1/integrations/github-owners/reconcile",
        json=request_data,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is False


def test_post_reconcile_requires_auth(
    client: TestClient,
    sample_reconcile_request: GithubOwnersReconcileRequest,
) -> None:
    """POST /reconcile requires authentication."""
    response = client.post(
        "/api/v1/integrations/github-owners/reconcile",
        json=sample_reconcile_request.model_dump(),
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_post_reconcile_invalid_request_body(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /reconcile rejects invalid request body."""
    response = client.post(
        "/api/v1/integrations/github-owners/reconcile",
        json={"invalid": "body"},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@patch("qontract_api.integrations.github_owners.router.wait_for_task_completion")
def test_get_task_status(
    mock_wait: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /reconcile/{task_id} returns task result."""
    expected_result = GithubOwnersTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        errors=[],
    )
    mock_wait.return_value = expected_result

    response = client.get(
        "/api/v1/integrations/github-owners/reconcile/test-task-id",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert data["actions"] == []
