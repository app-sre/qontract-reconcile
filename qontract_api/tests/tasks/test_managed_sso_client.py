"""Unit tests for managed-sso-client Celery task -- event publishing and lock keys."""

import inspect
from collections.abc import Callable
from unittest.mock import MagicMock, patch

from qontract_api.integrations.managed_sso_client.domain import (
    KeycloakInstanceRef,
    ManagedSsoClientDesiredState,
    OidcDesiredState,
)
from qontract_api.integrations.managed_sso_client.metrics import INTEGRATION_NAME
from qontract_api.integrations.managed_sso_client.schemas import (
    ManagedSsoClientAction,
    ManagedSsoClientActionCreate,
    ManagedSsoClientActionDelete,
    ManagedSsoClientTaskResult,
)
from qontract_api.integrations.managed_sso_client.tasks import (
    generate_lock_key,
    reconcile_managed_sso_client_task,
)
from qontract_api.models import Secret, TaskStatus


def _desired(client_id: str = "my-app-ci-bot") -> ManagedSsoClientDesiredState:
    return ManagedSsoClientDesiredState(
        client_id=client_id,
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


def _mock_self() -> MagicMock:
    mock = MagicMock()
    mock.request.id = "test-task-id"
    return mock


def _task_func() -> Callable:
    """Return the unwrapped task function (bypasses Celery + deduplication decorators)."""
    return inspect.unwrap(reconcile_managed_sso_client_task)


def _make_result(
    applied_actions: list[ManagedSsoClientAction] | None = None,
    errors: list[str] | None = None,
) -> ManagedSsoClientTaskResult:
    applied = applied_actions or []
    errs = errors or []
    return ManagedSsoClientTaskResult(
        status=TaskStatus.FAILED if errs else TaskStatus.SUCCESS,
        actions=applied,
        applied_actions=applied,
        applied_count=len(applied),
        errors=errs,
    )


def test_generate_lock_key_is_constant() -> None:
    """The management Vault prefix is server-configured, not client-supplied.

    So every reconcile call locks on the same key regardless of desired_clients.
    """
    key_a = generate_lock_key(MagicMock(), desired_clients=[_desired("a-bot")])
    key_b = generate_lock_key(
        MagicMock(), desired_clients=[_desired("a-bot"), _desired("b-bot")]
    )
    assert key_a == key_b == INTEGRATION_NAME


@patch("qontract_api.integrations.managed_sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_cache")
@patch("qontract_api.integrations.managed_sso_client.tasks.ManagedSsoClientService")
def test_publishes_success_event_for_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
) -> None:
    action = ManagedSsoClientActionCreate(
        client_id="my-app-ci-bot",
        tenant_secret_path="app-sre/managed-sso-client/output/my-app-ci-bot",
    )
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(_mock_self(), [_desired()], dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.managed-sso-client.create"
    assert published.data["client_id"] == "my-app-ci-bot"
    assert (
        published.data["tenant_secret_path"]
        == "app-sre/managed-sso-client/output/my-app-ci-bot"
    )


@patch("qontract_api.integrations.managed_sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_cache")
@patch("qontract_api.integrations.managed_sso_client.tasks.ManagedSsoClientService")
def test_publishes_error_event_for_each_error(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        errors=["my-app-ci-bot: Failed to execute action create: boom"]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(_mock_self(), [_desired()], dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.managed-sso-client.error"
    assert "boom" in published.data["error"]


@patch("qontract_api.integrations.managed_sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_cache")
@patch("qontract_api.integrations.managed_sso_client.tasks.ManagedSsoClientService")
def test_no_events_published_in_dry_run(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[ManagedSsoClientActionDelete(client_id="my-app-ci-bot")],
        errors=["some error"],
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(_mock_self(), [_desired()], dry_run=True)

    mock_event_manager.publish_event.assert_not_called()


@patch("qontract_api.integrations.managed_sso_client.tasks.get_event_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_secret_manager")
@patch("qontract_api.integrations.managed_sso_client.tasks.get_cache")
@patch("qontract_api.integrations.managed_sso_client.tasks.ManagedSsoClientService")
def test_task_returns_failed_result_on_unexpected_exception(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.side_effect = RuntimeError(
        "connection refused"
    )

    result = _task_func()(_mock_self(), [_desired()], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert "connection refused" in result.errors[0]
