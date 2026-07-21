"""Unit tests for sso_client Celery task — focusing on event publishing."""

import inspect
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from qontract_api.integrations.sso_client.domain import KeycloakInstanceSecret
from qontract_api.integrations.sso_client.schemas import (
    SsoClientActionCreate,
    SsoClientActionDelete,
    SsoClientTaskResult,
)
from qontract_api.integrations.sso_client.tasks import (
    generate_lock_key,
    reconcile_sso_client_task,
)
from qontract_api.models import Secret, TaskStatus

KEYCLOAK_SECRET = KeycloakInstanceSecret(
    url="https://issuer.example.com",
    secret=Secret(
        secret_manager_url="https://keycloak-vault.example.com",
        path="keycloak/instance1",
    ),
)
VAULT_TARGET = Secret(
    secret_manager_url="https://vault.example.com", path="rhidp/sso-client/prod"
)


@pytest.fixture
def mock_self() -> MagicMock:
    mock = MagicMock()
    mock.request.id = "test-task-id"
    return mock


def _task_func() -> Callable:
    """Return the unwrapped task function (bypasses Celery + deduplication decorators)."""
    return inspect.unwrap(reconcile_sso_client_task)


def _make_create_action(sso_client_id: str = "client-1") -> SsoClientActionCreate:
    return SsoClientActionCreate(
        sso_client_id=sso_client_id, cluster_name="my-cluster", auth_name="redhat-sso"
    )


def _make_result(
    applied_actions: list | None = None, errors: list[str] | None = None
) -> SsoClientTaskResult:
    applied = applied_actions or []
    errs = errors or []
    return SsoClientTaskResult(
        status=TaskStatus.FAILED if errs else TaskStatus.SUCCESS,
        actions=applied,
        applied_actions=applied,
        applied_count=len(applied),
        errors=errs,
    )


# ---------------------------------------------------------------------------
# generate_lock_key
# ---------------------------------------------------------------------------


def test_generate_lock_key() -> None:
    key = generate_lock_key(MagicMock(), "prod", VAULT_TARGET)
    assert key == "prod:rhidp/sso-client/prod"


# ---------------------------------------------------------------------------
# Event publishing — success events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_cache")
@patch("qontract_api.integrations.sso_client.tasks.SsoClientService")
def test_publishes_success_event_for_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    action = _make_create_action()
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.sso-client.create"
    assert published.data["sso_client_id"] == "client-1"


@patch("qontract_api.integrations.sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_cache")
@patch("qontract_api.integrations.sso_client.tasks.SsoClientService")
def test_publishes_one_event_per_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    actions = [
        _make_create_action("client-1"),
        SsoClientActionDelete(sso_client_id="client-2"),
    ]
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=actions
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False)

    assert mock_event_manager.publish_event.call_count == 2
    types = {c[0][0].type for c in mock_event_manager.publish_event.call_args_list}
    assert types == {"qontract-api.sso-client.create", "qontract-api.sso-client.delete"}


# ---------------------------------------------------------------------------
# Event publishing — error events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_cache")
@patch("qontract_api.integrations.sso_client.tasks.SsoClientService")
def test_publishes_error_event_for_each_error(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        errors=["client-1: Failed to execute action create: boom"]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.sso-client.error"
    assert "boom" in published.data["error"]


# ---------------------------------------------------------------------------
# Event publishing — suppression cases
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_cache")
@patch("qontract_api.integrations.sso_client.tasks.SsoClientService")
def test_no_events_published_in_dry_run(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[_make_create_action()], errors=["some error"]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=True)

    mock_event_manager.publish_event.assert_not_called()


@patch("qontract_api.integrations.sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_cache")
@patch("qontract_api.integrations.sso_client.tasks.SsoClientService")
def test_no_events_published_when_event_manager_disabled(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[_make_create_action()], errors=["some error"]
    )
    mock_get_event_manager.return_value = None

    result = _task_func()(
        mock_self, "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False
    )
    assert result.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.sso_client.tasks.get_cache")
@patch("qontract_api.integrations.sso_client.tasks.SsoClientService")
def test_task_returns_failed_result_on_unexpected_exception(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.side_effect = RuntimeError(
        "connection refused"
    )

    result = _task_func()(
        mock_self, "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert "connection refused" in result.errors[0]
