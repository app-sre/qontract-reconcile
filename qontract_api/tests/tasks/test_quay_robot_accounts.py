"""Unit tests for quay-robot-accounts Celery task event publishing."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from qontract_api.integrations.quay_robot_accounts.domain import (
    QuayOrgDesiredState,
    QuayRobotDesiredState,
)
from qontract_api.integrations.quay_robot_accounts.schemas import (
    QuayRobotAccountsTaskResult,
    QuayRobotActionCreate,
)
from qontract_api.integrations.quay_robot_accounts.tasks import (
    generate_lock_key,
    reconcile_quay_robot_accounts_task,
)
from qontract_api.models import Secret, TaskStatus


@pytest.fixture
def sample_org() -> QuayOrgDesiredState:
    return QuayOrgDesiredState(
        instance_name="quay-io",
        instance_url="quay.io",
        org_name="test-org",
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path="app-sre/creds/quay",
            field="token",
            version=1,
        ),
        managed_robot_accounts=True,
        robots=[QuayRobotDesiredState(name="ci-bot")],
    )


@pytest.fixture
def mock_self() -> MagicMock:
    mock = MagicMock()
    mock.request.id = "test-task-id"
    return mock


def _task_func() -> Callable:
    return reconcile_quay_robot_accounts_task.__wrapped__.__wrapped__


def _make_action() -> QuayRobotActionCreate:
    return QuayRobotActionCreate(
        instance_name="quay-io",
        org_name="test-org",
        robot_name="ci-bot",
    )


def _make_result(
    applied_actions: list | None = None,
    errors: list[str] | None = None,
) -> QuayRobotAccountsTaskResult:
    applied = applied_actions or []
    errs = errors or []
    return QuayRobotAccountsTaskResult(
        status=TaskStatus.FAILED if errs else TaskStatus.SUCCESS,
        actions=applied,
        applied_actions=applied,
        applied_count=len(applied),
        errors=errs,
    )


def test_generate_lock_key_sorted(sample_org: QuayOrgDesiredState) -> None:
    other = sample_org.model_copy(update={"org_name": "aaa-org"})
    key = generate_lock_key(MagicMock(), [sample_org, other])
    assert key == "quay-io/aaa-org,quay-io/test-org"


@patch("qontract_api.integrations.quay_robot_accounts.tasks.get_event_manager")
@patch("qontract_api.integrations.quay_robot_accounts.tasks.get_secret_manager")
@patch("qontract_api.integrations.quay_robot_accounts.tasks.get_cache")
@patch("qontract_api.integrations.quay_robot_accounts.tasks.QuayRobotAccountsService")
def test_publishes_success_event_for_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: QuayOrgDesiredState,
) -> None:
    action = _make_action()
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, [sample_org], dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.quay-robot-accounts.create"
    assert published.data["robot_name"] == "ci-bot"


@patch("qontract_api.integrations.quay_robot_accounts.tasks.get_event_manager")
@patch("qontract_api.integrations.quay_robot_accounts.tasks.get_secret_manager")
@patch("qontract_api.integrations.quay_robot_accounts.tasks.get_cache")
@patch("qontract_api.integrations.quay_robot_accounts.tasks.QuayRobotAccountsService")
def test_no_events_published_in_dry_run(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: QuayOrgDesiredState,
) -> None:
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[_make_action()],
        errors=["some error"],
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, [sample_org], dry_run=True)

    mock_event_manager.publish_event.assert_not_called()
