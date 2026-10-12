"""Unit tests for managed-sso-client router endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.managed_sso_client.domain import (
    KeycloakInstanceRef,
    ManagedSsoClientDesiredState,
    OidcDesiredState,
)
from qontract_api.integrations.managed_sso_client.schemas import (
    ManagedSsoClientReconcileRequest,
    ManagedSsoClientTaskResult,
)
from qontract_api.models import Secret, TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_client() -> ManagedSsoClientDesiredState:
    return ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=KeycloakInstanceRef(
            url="https://sso.example.com/auth/realms/example-realm",
            initial_access_token=Secret(
                secret_manager_url="https://vault.example.com",
                path="app-sre/keycloak/iat",
                field="token",
            ),
        ),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
    )


@pytest.fixture
def sample_reconcile_request(
    sample_client: ManagedSsoClientDesiredState,
) -> ManagedSsoClientReconcileRequest:
    return ManagedSsoClientReconcileRequest(
        desired_clients=[sample_client],
        dry_run=True,
    )


@patch(
    "qontract_api.integrations.managed_sso_client.router.reconcile_managed_sso_client_task"
)
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ManagedSsoClientReconcileRequest,
) -> None:
    response = client.post(
        "/api/v1/integrations/managed-sso-client/reconcile",
        json=sample_reconcile_request.model_dump(mode="json"),
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
    "qontract_api.integrations.managed_sso_client.router.reconcile_managed_sso_client_task"
)
def test_post_reconcile_dry_run_false(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_client: ManagedSsoClientDesiredState,
) -> None:
    response = client.post(
        "/api/v1/integrations/managed-sso-client/reconcile",
        json=ManagedSsoClientReconcileRequest(
            desired_clients=[sample_client],
            dry_run=False,
        ).model_dump(mode="json"),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is False
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


def test_post_reconcile_requires_auth(
    client: TestClient,
    sample_reconcile_request: ManagedSsoClientReconcileRequest,
) -> None:
    response = client.post(
        "/api/v1/integrations/managed-sso-client/reconcile",
        json=sample_reconcile_request.model_dump(mode="json"),
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


@patch("qontract_api.integrations.managed_sso_client.router.wait_for_task_completion")
def test_get_task_status(
    mock_wait: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_wait.return_value = ManagedSsoClientTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        errors=[],
    )
    response = client.get(
        "/api/v1/integrations/managed-sso-client/reconcile/test-task-id",
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == TaskStatus.SUCCESS.value
