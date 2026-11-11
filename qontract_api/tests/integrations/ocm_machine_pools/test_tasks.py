"""Tests for ocm-machine-pools tasks."""

from unittest.mock import MagicMock, patch

from qontract_api.integrations.ocm_machine_pools.schemas import (
    OcmMachinePoolsTaskResult,
)
from qontract_api.integrations.ocm_machine_pools.tasks import (
    generate_lock_key,
    reconcile_ocm_machine_pools_task,
)
from qontract_api.models import TaskStatus
from qontract_api.ocm.domain import OcmConnectionParams

OCM_CONNECTION = OcmConnectionParams(
    secret_manager_url="https://vault.example.com",
    path="ocm/prod",
    ocm_url="https://api.openshift.com",
    access_token_url="https://sso.redhat.com/token",
    access_token_client_id="client-id",
)


def test_generate_lock_key() -> None:
    """Lock key deduplicates reconciles per OCM environment."""
    key = generate_lock_key(MagicMock(), "prod", OCM_CONNECTION)
    assert key == "ocm-machine-pools:prod:https://api.openshift.com"


@patch("qontract_api.integrations.ocm_machine_pools.tasks.get_cache")
@patch("qontract_api.integrations.ocm_machine_pools.tasks.get_secret_manager")
def test_task_invokes_service(
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """The Celery task delegates to OcmMachinePoolsService.reconcile."""
    with patch(
        "qontract_api.integrations.ocm_machine_pools.tasks.OcmMachinePoolsService"
    ) as mock_service_cls:
        mock_service = mock_service_cls.return_value
        mock_service.reconcile.return_value = OcmMachinePoolsTaskResult(
            status=TaskStatus.SUCCESS, actions=[], applied_count=0, errors=[]
        )

        result = reconcile_ocm_machine_pools_task(
            "prod",
            OCM_CONNECTION,
            [],
            dry_run=True,
        )

    mock_service.reconcile.assert_called_once_with(
        ocm_environment="prod",
        ocm_connection=OCM_CONNECTION,
        clusters=[],
        dry_run=True,
    )
    assert result.status == TaskStatus.SUCCESS


@patch("qontract_api.integrations.ocm_machine_pools.tasks.get_cache")
@patch("qontract_api.integrations.ocm_machine_pools.tasks.get_secret_manager")
def test_task_failure_returns_failed_result(
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """An unexpected exception yields a FAILED task result, not a crash."""
    with patch(
        "qontract_api.integrations.ocm_machine_pools.tasks.OcmMachinePoolsService"
    ) as mock_service_cls:
        mock_service_cls.side_effect = RuntimeError("boom")

        result = reconcile_ocm_machine_pools_task(
            "prod",
            OCM_CONNECTION,
            [],
            dry_run=True,
        )

    assert result.status == TaskStatus.FAILED
    assert any("boom" in error for error in result.errors)


@patch("qontract_api.integrations.ocm_machine_pools.tasks.get_cache")
@patch("qontract_api.integrations.ocm_machine_pools.tasks.get_secret_manager")
@patch("qontract_api.integrations.ocm_machine_pools.tasks.get_event_manager")
@patch("qontract_api.tasks._deduplication.get_cache")
def test_task_publishes_events_for_applied_actions(
    mock_dedup_cache: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """Applied actions are published as events on non-dry-run runs."""
    from qontract_api.integrations.ocm_machine_pools.schemas import (
        OcmMachinePoolsActionCreateMachinePool,
    )

    action = OcmMachinePoolsActionCreateMachinePool(
        cluster="osd-cluster", pool_id="worker"
    )
    event_manager = mock_get_event_manager.return_value
    with patch(
        "qontract_api.integrations.ocm_machine_pools.tasks.OcmMachinePoolsService"
    ) as mock_service_cls:
        mock_service_cls.return_value.reconcile.return_value = (
            OcmMachinePoolsTaskResult(
                status=TaskStatus.SUCCESS,
                actions=[action],
                applied_actions=[action],
                applied_count=1,
                errors=[],
            )
        )

        result = reconcile_ocm_machine_pools_task(
            "prod", OCM_CONNECTION, [], dry_run=False
        )

    assert result.applied_count == 1
    event_manager.publish_event.assert_called_once()
    event = event_manager.publish_event.call_args.args[0]
    assert event.type == "qontract-api.ocm-machine-pools.create_machine_pool"
