"""Unit tests for GitLab projects router endpoints."""

from http import HTTPStatus
from typing import TypedDict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.gitlab_projects.schemas import (
    GitlabProjectActionCreate,
    GitlabProjectsTaskResult,
)
from qontract_api.models import TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD


class _TokenPayload(TypedDict):
    secret_manager_url: str
    path: str


class _ProjectPayload(TypedDict):
    name: str
    is_saas_bundle: bool


class _GroupPayload(TypedDict):
    group: str
    projects: list[_ProjectPayload]


class _InstancePayload(TypedDict):
    name: str
    url: str
    token: _TokenPayload
    groups: list[_GroupPayload]


class ReconcileRequestPayload(TypedDict):
    instances: list[_InstancePayload]
    dry_run: bool


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_reconcile_request() -> ReconcileRequestPayload:
    return {
        "instances": [
            {
                "name": "gitlab-cee",
                "url": "https://gitlab.cee.redhat.com",
                "token": {
                    "secret_manager_url": "https://vault.example.com",
                    "path": "secret/gitlab/gitlab-cee/token",
                },
                "groups": [
                    {
                        "group": "team",
                        "projects": [{"name": "myproj", "is_saas_bundle": False}],
                    }
                ],
            }
        ],
        "dry_run": True,
    }


# ---------------------------------------------------------------------------
# POST /reconcile
# ---------------------------------------------------------------------------


@patch(
    "qontract_api.integrations.gitlab_projects.router.reconcile_gitlab_projects_task"
)
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    response = client.post(
        "/api/v1/integrations/gitlab-projects/reconcile",
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
    assert len(call_kwargs["instances"]) == 1


@patch(
    "qontract_api.integrations.gitlab_projects.router.reconcile_gitlab_projects_task"
)
def test_post_reconcile_dry_run_true_uses_mr_check_queue(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    sample_reconcile_request["dry_run"] = True
    response = client.post(
        "/api/v1/integrations/gitlab-projects/reconcile",
        json=sample_reconcile_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_MR_CHECK


@patch(
    "qontract_api.integrations.gitlab_projects.router.reconcile_gitlab_projects_task"
)
def test_post_reconcile_dry_run_false_uses_prod_queue(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    sample_reconcile_request["dry_run"] = False
    response = client.post(
        "/api/v1/integrations/gitlab-projects/reconcile",
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
        "/api/v1/integrations/gitlab-projects/reconcile",
        json=sample_reconcile_request,
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_post_reconcile_invalid_request_missing_instance_fields(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/integrations/gitlab-projects/reconcile",
        json={"instances": [{"name": "gitlab-cee"}], "dry_run": True},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_post_reconcile_invalid_request_missing_instances(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/integrations/gitlab-projects/reconcile",
        json={"dry_run": True},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_post_reconcile_duplicate_project_names_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: ReconcileRequestPayload,
) -> None:
    sample_reconcile_request["instances"][0]["groups"][0]["projects"] = [
        {"name": "myproj", "is_saas_bundle": False},
        {"name": "myproj", "is_saas_bundle": True},
    ]
    response = client.post(
        "/api/v1/integrations/gitlab-projects/reconcile",
        json=sample_reconcile_request,
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "duplicate project names" in response.text


# ---------------------------------------------------------------------------
# GET /reconcile/{task_id}  # ruff: ignore[commented-out-code]
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.gitlab_projects.router.get_celery_task_result")
def test_get_task_status_pending(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = GitlabProjectsTaskResult(status=TaskStatus.PENDING)

    response = client.get(
        "/api/v1/integrations/gitlab-projects/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.PENDING.value


@patch("qontract_api.integrations.gitlab_projects.router.get_celery_task_result")
def test_get_task_status_success(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = GitlabProjectsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            GitlabProjectActionCreate(
                instance="gitlab-cee", group="team", project_name="myproj"
            )
        ],
        applied_actions=[],
        applied_count=0,
    )

    response = client.get(
        "/api/v1/integrations/gitlab-projects/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert len(data["actions"]) == 1
    assert data["actions"][0]["action_type"] == "create"


@patch("qontract_api.integrations.gitlab_projects.router.get_celery_task_result")
def test_get_task_status_failed(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = GitlabProjectsTaskResult(
        status=TaskStatus.FAILED,
        errors=["gitlab-cee/team: GitLab API error"],
    )

    response = client.get(
        "/api/v1/integrations/gitlab-projects/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.FAILED.value
    assert len(data["errors"]) == 1
    assert "GitLab API error" in data["errors"][0]


@patch("qontract_api.integrations.gitlab_projects.router.get_celery_task_result")
def test_get_task_status_blocking_waits_for_completion(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.side_effect = [
        GitlabProjectsTaskResult(status=TaskStatus.PENDING),
        GitlabProjectsTaskResult(status=TaskStatus.SUCCESS),
    ]

    response = client.get(
        "/api/v1/integrations/gitlab-projects/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 5},
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert mock_get_result.call_count >= 2


@patch("qontract_api.integrations.gitlab_projects.router.get_celery_task_result")
def test_get_task_status_blocking_timeout_returns_408(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    mock_get_result.return_value = GitlabProjectsTaskResult(status=TaskStatus.PENDING)

    response = client.get(
        "/api/v1/integrations/gitlab-projects/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 1},
    )

    assert response.status_code == HTTPStatus.REQUEST_TIMEOUT


def test_get_task_status_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/integrations/gitlab-projects/reconcile/task-123")
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_get_task_status_timeout_too_large(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/api/v1/integrations/gitlab-projects/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 99999},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_get_task_status_timeout_zero_invalid(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/api/v1/integrations/gitlab-projects/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 0},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
