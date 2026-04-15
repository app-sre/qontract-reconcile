"""Unit tests for glitchtip Celery task — focusing on event publishing."""

import inspect
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from qontract_api.integrations.glitchtip.domain import GIInstance, GIOrganization
from qontract_api.integrations.glitchtip.schemas import (
    GlitchtipActionInviteUser,
    GlitchtipTaskResult,
)
from qontract_api.integrations.glitchtip.tasks import (
    generate_lock_key,
    reconcile_glitchtip_task,
)
from qontract_api.models import Secret, TaskStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_token() -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/glitchtip/token",
    )


@pytest.fixture
def test_automation_email_secret() -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/glitchtip/automation-email",
    )


@pytest.fixture
def sample_instances(
    test_token: Secret, test_automation_email_secret: Secret
) -> list[GIInstance]:
    return [
        GIInstance(
            name="instance-1",
            console_url="https://glitchtip.example.com",
            token=test_token,
            automation_user_email=test_automation_email_secret,
            organizations=[
                GIOrganization(name="my-org", teams=[], projects=[], users=[])
            ],
        )
    ]


@pytest.fixture
def mock_self() -> MagicMock:
    mock = MagicMock()
    mock.request.id = "test-task-id"
    return mock


def _task_func() -> Callable:
    """Return the unwrapped task function (bypasses Celery + deduplication decorators)."""
    return inspect.unwrap(reconcile_glitchtip_task)


def _make_action(
    org: str = "my-org", email: str = "user@example.com"
) -> GlitchtipActionInviteUser:
    return GlitchtipActionInviteUser(
        instance="my-instance", organization=org, email=email, role="member"
    )


def _make_result(
    applied_actions: list[GlitchtipActionInviteUser] | None = None,
    errors: list[str] | None = None,
) -> GlitchtipTaskResult:
    applied = applied_actions or []
    errs = errors or []
    return GlitchtipTaskResult(
        status=TaskStatus.FAILED if errs else TaskStatus.SUCCESS,
        actions=applied,
        applied_actions=applied,
        applied_count=len(applied),
        errors=errs,
    )


# ---------------------------------------------------------------------------
# generate_lock_key
# ---------------------------------------------------------------------------


def test_generate_lock_key_single_instance(
    sample_instances: list[GIInstance],
) -> None:
    assert generate_lock_key(MagicMock(), sample_instances) == "instance-1"


def test_generate_lock_key_sorted(
    test_token: Secret, test_automation_email_secret: Secret
) -> None:
    def _instance(name: str) -> GIInstance:
        return GIInstance(
            name=name,
            console_url="https://glitchtip.example.com",
            token=test_token,
            automation_user_email=test_automation_email_secret,
            organizations=[],
        )

    key = generate_lock_key(MagicMock(), [_instance("inst-b"), _instance("inst-a")])
    assert key == "inst-a,inst-b"


# ---------------------------------------------------------------------------
# Event publishing — success events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.glitchtip.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_secret_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip.tasks.GlitchtipService")
def test_publishes_success_event_for_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_instances: list[GIInstance],
) -> None:
    """A success event is published for each successfully applied action."""
    action = _make_action()
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, sample_instances, dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.glitchtip.invite_user"
    assert published.data["email"] == "user@example.com"


@patch("qontract_api.integrations.glitchtip.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_secret_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip.tasks.GlitchtipService")
def test_publishes_one_event_per_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_instances: list[GIInstance],
) -> None:
    """One success event is published per applied action."""
    actions = [
        _make_action(email="alice@example.com"),
        _make_action(email="bob@example.com"),
    ]
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=actions
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, sample_instances, dry_run=False)

    assert mock_event_manager.publish_event.call_count == 2
    types = [c[0][0].type for c in mock_event_manager.publish_event.call_args_list]
    assert all(t == "qontract-api.glitchtip.invite_user" for t in types)


# ---------------------------------------------------------------------------
# Event publishing — error events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.glitchtip.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_secret_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip.tasks.GlitchtipService")
def test_publishes_error_event_for_each_error(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_instances: list[GIInstance],
) -> None:
    """An error event is published for each reconciliation error."""
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        errors=["instance-1/my-org/invite_user: 403 Forbidden"]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, sample_instances, dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.glitchtip.error"
    assert "403 Forbidden" in published.data["error"]


@patch("qontract_api.integrations.glitchtip.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_secret_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip.tasks.GlitchtipService")
def test_publishes_both_event_types_on_partial_failure(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_instances: list[GIInstance],
) -> None:
    """Both success and error events are published when some actions apply and some fail."""
    applied = _make_action(email="alice@example.com")
    mock_service_cls.return_value.reconcile.return_value = GlitchtipTaskResult(
        status=TaskStatus.FAILED,
        actions=[applied, _make_action(email="bob@example.com")],
        applied_actions=[applied],
        applied_count=1,
        errors=["instance-1/my-org/invite_user: 403 Forbidden"],
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, sample_instances, dry_run=False)

    assert mock_event_manager.publish_event.call_count == 2
    event_types = {
        c[0][0].type for c in mock_event_manager.publish_event.call_args_list
    }
    assert event_types == {
        "qontract-api.glitchtip.invite_user",
        "qontract-api.glitchtip.error",
    }


# ---------------------------------------------------------------------------
# Event publishing — suppression cases
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.glitchtip.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_secret_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip.tasks.GlitchtipService")
def test_no_events_published_in_dry_run(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_instances: list[GIInstance],
) -> None:
    """No events are published in dry-run mode."""
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[_make_action()],
        errors=["some error"],
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, sample_instances, dry_run=True)

    mock_event_manager.publish_event.assert_not_called()


@patch("qontract_api.integrations.glitchtip.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_secret_manager")
@patch("qontract_api.integrations.glitchtip.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip.tasks.GlitchtipService")
def test_no_events_published_when_event_manager_disabled(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_instances: list[GIInstance],
) -> None:
    """No events are published when the event manager is not configured (returns None)."""
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[_make_action()],
        errors=["some error"],
    )
    mock_get_event_manager.return_value = None

    result = _task_func()(mock_self, sample_instances, dry_run=False)
    assert (
        result.status == TaskStatus.FAILED
    )  # errors present → failed, no exception raised
