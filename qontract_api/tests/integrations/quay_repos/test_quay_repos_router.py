"""Unit tests for Quay repos router endpoints."""

from http import HTTPStatus
from typing import TypedDict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.quay_repos.schemas import (
    QuayRepoActionCreate,
    QuayReposTaskResult,
)
from qontract_api.models import TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD


class _AutomationTokenPayload(TypedDict):
    secret_manager_url: str
    path: str


class _RepoPayload(TypedDict):
    name: str
    public: bool
    description: str


class _OrgPayload(TypedDict):
    instance: str
    org_name: str
    base_url: str
    automation_token: _AutomationTokenPayload
    managed_repos: bool
    repos: list[_RepoPayload]


class ReconcileRequestPayload(TypedDict):
    orgs: list[_OrgPayload]
    dry_run: bool


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_reconcile_request() -> ReconcileRequestPayload:
    return {
        "orgs": [
            {
                "instance": "quay.io",
                "org_name": "myorg",
                "base_url": "https://quay.io",
                "automation_token": {
                    "secret_manager_url": "https://vault.example.com",
                    "path": "secret/quay/myorg",
                },
                "managed_repos": True,
                "repos": [
                    {"name": "myrepo", "public": True, "description": "Test repo"}
                ],
            }
        ],
        "dry_run": True,
    }


# ---------------------------------------------------------------------------
# POST /reconcile
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.quay_repos.router.reconcile_quay_repos_task")
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    response = client.post(
        "/api/v1/integrations/quay-repos/reconcile",
        json=sample_reconcile_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert data["id"] == request_id
    assert data["status"] == TaskStatus.PENDING.value
    assert "status_url" in data
    assert f"/reconcile/{request_id}" in data["status_url"]

    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is True
    assert len(call_kwargs["orgs"]) == 1


@patch("qontract_api.integrations.quay_repos.router.reconcile_quay_repos_task")
def test_post_reconcile_dry_run_true_uses_mr_check_queue(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    sample_reconcile_request["dry_run"] = True
    response = client.post(
        "/api/v1/integrations/quay-repos/reconcile",
        json=sample_reconcile_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_MR_CHECK


@patch("qontract_api.integrations.quay_repos.router.reconcile_quay_repos_task")
def test_post_reconcile_dry_run_false_uses_prod_queue(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    sample_reconcile_request["dry_run"] = False
    response = client.post(
        "/api/v1/integrations/quay-repos/reconcile",
        json=sample_reconcile_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


def test_post_reconcile_requires_auth(
    client: TestClient,
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    response = client.post(
        "/api/v1/integrations/quay-repos/reconcile",
        json=sample_reconcile_request,
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_post_reconcile_invalid_request_missing_org_fields(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/integrations/quay-repos/reconcile",
        json={"orgs": [{"instance": "quay.io"}], "dry_run": True},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_post_reconcile_invalid_request_missing_orgs(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/integrations/quay-repos/reconcile",
        json={"dry_run": True},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_post_reconcile_duplicate_repo_names_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    sample_reconcile_request["orgs"][0]["repos"] = [
        {"name": "myrepo", "public": True, "description": "first"},
        {"name": "myrepo", "public": False, "description": "second"},
    ]
    response = client.post(
        "/api/v1/integrations/quay-repos/reconcile",
        json=sample_reconcile_request,
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "duplicate repo names" in response.text


# ---------------------------------------------------------------------------
# GET /reconcile/{task_id}  # ruff: ignore[commented-out-code]
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.quay_repos.router.get_celery_task_result")
def test_get_task_status_pending(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = QuayReposTaskResult(status=TaskStatus.PENDING)

    response = client.get(
        "/api/v1/integrations/quay-repos/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.PENDING.value


@patch("qontract_api.integrations.quay_repos.router.get_celery_task_result")
def test_get_task_status_success(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = QuayReposTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            QuayRepoActionCreate(
                instance="quay.io",
                org_name="myorg",
                repo_name="myrepo",
                public=True,
                description="desc",
            )
        ],
        applied_actions=[],
        applied_count=0,
    )

    response = client.get(
        "/api/v1/integrations/quay-repos/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert len(data["actions"]) == 1
    assert data["actions"][0]["action_type"] == "create"


@patch("qontract_api.integrations.quay_repos.router.get_celery_task_result")
def test_get_task_status_failed(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = QuayReposTaskResult(
        status=TaskStatus.FAILED,
        errors=["quay.io/myorg: Quay API error"],
    )

    response = client.get(
        "/api/v1/integrations/quay-repos/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.FAILED.value
    assert len(data["errors"]) == 1
    assert "Quay API error" in data["errors"][0]


@patch("qontract_api.integrations.quay_repos.router.get_celery_task_result")
def test_get_task_status_blocking_waits_for_completion(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.side_effect = [
        QuayReposTaskResult(status=TaskStatus.PENDING),
        QuayReposTaskResult(status=TaskStatus.SUCCESS),
    ]

    response = client.get(
        "/api/v1/integrations/quay-repos/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 5},
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert mock_get_result.call_count >= 2


@patch("qontract_api.integrations.quay_repos.router.get_celery_task_result")
def test_get_task_status_blocking_timeout_returns_408(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = QuayReposTaskResult(status=TaskStatus.PENDING)

    response = client.get(
        "/api/v1/integrations/quay-repos/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 1},
    )

    assert response.status_code == HTTPStatus.REQUEST_TIMEOUT


def test_get_task_status_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/integrations/quay-repos/reconcile/task-123")
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_get_task_status_timeout_too_large(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/api/v1/integrations/quay-repos/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 99999},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_get_task_status_timeout_zero_invalid(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/api/v1/integrations/quay-repos/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 0},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
