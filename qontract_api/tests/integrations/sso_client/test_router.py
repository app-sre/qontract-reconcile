"""Unit tests for RHIDP SSO client reconciliation router endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.sso_client.domain import KeycloakInstanceSecret
from qontract_api.integrations.sso_client.schemas import (
    SsoClientCreateManualRequest,
    SsoClientCreateManualResult,
    SsoClientReconcileRequest,
    SsoClientTaskResult,
)
from qontract_api.models import Secret, TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD

ENDPOINT = "/api/v1/integrations/sso-client/reconcile"
MANUAL_ENDPOINT = "/api/v1/integrations/sso-client/manual"


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_reconcile_request() -> SsoClientReconcileRequest:
    return SsoClientReconcileRequest(
        ocm_environment="prod",
        clusters=[],
        keycloak_secrets=[
            KeycloakInstanceSecret(
                url="https://issuer.example.com",
                secret=Secret(
                    secret_manager_url="https://keycloak-vault.example.com",
                    path="keycloak/instance1",
                ),
            )
        ],
        vault_target=Secret(
            secret_manager_url="https://vault.example.com",
            path="rhidp/sso-client/prod",
        ),
        dry_run=True,
    )


@patch("qontract_api.integrations.sso_client.router.reconcile_sso_client_task")
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: SsoClientReconcileRequest,
) -> None:
    """Test POST /reconcile queues a Celery task and returns task ID."""
    response = client.post(
        ENDPOINT, json=sample_reconcile_request.model_dump(), headers=auth_headers
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert data["id"] == request_id
    assert data["status"] == TaskStatus.PENDING.value
    assert f"/reconcile/{request_id}" in data["status_url"]

    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["ocm_environment"] == "prod"
    assert call_kwargs["dry_run"] is True
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_MR_CHECK


@patch("qontract_api.integrations.sso_client.router.reconcile_sso_client_task")
def test_post_reconcile_dry_run_false_uses_prod_queue(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: SsoClientReconcileRequest,
) -> None:
    request_data = sample_reconcile_request.model_dump()
    request_data["dry_run"] = False

    response = client.post(ENDPOINT, json=request_data, headers=auth_headers)

    assert response.status_code == HTTPStatus.ACCEPTED
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is False
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


def test_post_reconcile_requires_auth(
    client: TestClient, sample_reconcile_request: SsoClientReconcileRequest
) -> None:
    response = client.post(ENDPOINT, json=sample_reconcile_request.model_dump())
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_post_reconcile_invalid_body(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(ENDPOINT, json={"invalid": "body"}, headers=auth_headers)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@patch("qontract_api.integrations.sso_client.router.wait_for_task_completion")
def test_get_task_status(
    mock_wait: MagicMock, client: TestClient, auth_headers: dict[str, str]
) -> None:
    expected_result = SsoClientTaskResult(
        status=TaskStatus.SUCCESS, actions=[], applied_count=0, errors=[]
    )
    mock_wait.return_value = expected_result

    response = client.get(f"{ENDPOINT}/test-task-id", headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == TaskStatus.SUCCESS.value


@pytest.fixture
def sample_create_manual_request() -> SsoClientCreateManualRequest:
    return SsoClientCreateManualRequest(
        client_name="my-manual-client",
        redirect_uris=["https://example.org/login"],
        keycloak_instance=KeycloakInstanceSecret(
            url="https://issuer.example.com",
            secret=Secret(
                secret_manager_url="https://vault.corp.redhat.com:8200",
                path="apps/sso-iat/share-with/app/ai-app-sre/iat",
            ),
        ),
    )


@patch("qontract_api.integrations.sso_client.router.create_manual_sso_client_task")
def test_post_manual_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_create_manual_request: SsoClientCreateManualRequest,
) -> None:
    """Test POST /manual queues a Celery task and returns task ID."""
    response = client.post(
        MANUAL_ENDPOINT,
        json=sample_create_manual_request.model_dump(),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert data["id"] == request_id
    assert data["status"] == TaskStatus.PENDING.value
    assert f"/manual/{request_id}" in data["status_url"]

    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["request"].client_name == "my-manual-client"
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


def test_post_manual_requires_auth(
    client: TestClient, sample_create_manual_request: SsoClientCreateManualRequest
) -> None:
    response = client.post(
        MANUAL_ENDPOINT, json=sample_create_manual_request.model_dump()
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_post_manual_invalid_body(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        MANUAL_ENDPOINT, json={"invalid": "body"}, headers=auth_headers
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@patch("qontract_api.integrations.sso_client.router.wait_for_task_completion")
def test_get_manual_task_status(
    mock_wait: MagicMock, client: TestClient, auth_headers: dict[str, str]
) -> None:
    expected_result = SsoClientCreateManualResult(
        status=TaskStatus.SUCCESS,
        applied_count=1,
        vault_secret_path="app-sre/integrations-throughput/rhidp/manual/my-manual-client",
    )
    mock_wait.return_value = expected_result

    response = client.get(f"{MANUAL_ENDPOINT}/test-task-id", headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == TaskStatus.SUCCESS.value
    assert (
        response.json()["vault_secret_path"]
        == "app-sre/integrations-throughput/rhidp/manual/my-manual-client"
    )
