"""Unit tests for quay-robot-accounts router endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.quay_robot_accounts.domain import (
    QuayOrgDesiredState,
    QuayRobotDesiredState,
)
from qontract_api.integrations.quay_robot_accounts.schemas import (
    QuayRobotAccountsReconcileRequest,
    QuayRobotAccountsTaskResult,
)
from qontract_api.models import Secret, TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_org() -> QuayOrgDesiredState:
    return QuayOrgDesiredState(
        instance_name="quay-io",
        instance_url="quay.io",
        org_name="test-org",
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path="secret/quay/token",
        ),
        managed_robot_accounts=True,
        robots=[QuayRobotDesiredState(name="ci-bot")],
    )


@pytest.fixture
def sample_reconcile_request(
    sample_org: QuayOrgDesiredState,
) -> QuayRobotAccountsReconcileRequest:
    return QuayRobotAccountsReconcileRequest(
        organizations=[sample_org],
        dry_run=True,
    )


@patch(
    "qontract_api.integrations.quay_robot_accounts.router.reconcile_quay_robot_accounts_task"
)
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: QuayRobotAccountsReconcileRequest,
) -> None:
    response = client.post(
        "/api/v1/integrations/quay-robot-accounts/reconcile",
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
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_MR_CHECK


@patch(
    "qontract_api.integrations.quay_robot_accounts.router.reconcile_quay_robot_accounts_task"
)
def test_post_reconcile_dry_run_false(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_org: QuayOrgDesiredState,
) -> None:
    response = client.post(
        "/api/v1/integrations/quay-robot-accounts/reconcile",
        json={
            "organizations": [sample_org.model_dump()],
            "dry_run": False,
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is False
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


def test_post_reconcile_requires_auth(
    client: TestClient,
    sample_reconcile_request: QuayRobotAccountsReconcileRequest,
) -> None:
    response = client.post(
        "/api/v1/integrations/quay-robot-accounts/reconcile",
        json=sample_reconcile_request.model_dump(),
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


@patch("qontract_api.integrations.quay_robot_accounts.router.wait_for_task_completion")
def test_get_task_status(
    mock_wait: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_wait.return_value = QuayRobotAccountsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        errors=[],
    )
    response = client.get(
        "/api/v1/integrations/quay-robot-accounts/reconcile/test-task-id",
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == TaskStatus.SUCCESS.value
