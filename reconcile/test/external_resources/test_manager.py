from datetime import datetime
from typing import cast
from unittest.mock import Mock

import pytest
from pytest import fixture
from pytest_mock import MockerFixture

from reconcile.external_resources.manager import (
    ExternalResourceDryRunsValidator,
    ExternalResourcesManager,
    ReconcileStatus,
    ReconciliationStatus,
    ResourceStatus,
    setup_factories,
)
from reconcile.external_resources.model import (
    Action,
    ExternalResourcesInventory,
    ModuleInventory,
    Reconciliation,
)
from reconcile.external_resources.reconciler import ExternalResourcesReconciler
from reconcile.external_resources.state import (
    ExternalResourcesStateDynamoDB,
    ExternalResourceState,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)


@fixture
def manager(
    mocker: MockerFixture,
    settings: ExternalResourcesSettingsV1,
    module_inventory: ModuleInventory,
) -> ExternalResourcesManager:
    er_inventory = ExternalResourcesInventory([])
    state_mgr = Mock(spec=ExternalResourcesStateDynamoDB)
    secret_reader = Mock()
    reconciler = Mock(spec=ExternalResourcesReconciler)
    secrets_reconciler = Mock()
    factories = setup_factories(settings, module_inventory, er_inventory, secret_reader)
    dry_runs_validator = ExternalResourceDryRunsValidator(state_mgr, er_inventory)

    return ExternalResourcesManager(
        secret_reader=secret_reader,
        state_manager=Mock(spec=ExternalResourcesStateDynamoDB),
        settings=settings,
        module_inventory=module_inventory,
        reconciler=reconciler,
        factories=factories,
        er_inventory=er_inventory,
        secrets_reconciler=secrets_reconciler,
        thread_pool_size=1,
        dry_runs_validator=dry_runs_validator,
    )


@pytest.mark.parametrize(
    "action,status,expected",
    [
        (Action.APPLY, ResourceStatus.NOT_EXISTS, True),
        (Action.APPLY, ResourceStatus.ERROR, True),
        (
            Action.APPLY,
            ResourceStatus.CREATED,
            True,
        ),  # Digests are different. It shuold reconcile
        (Action.DESTROY, ResourceStatus.CREATED, True),
        (Action.DESTROY, ResourceStatus.ERROR, True),
        (Action.DESTROY, ResourceStatus.NOT_EXISTS, False),
    ],
)
def test_resource_needs_reconciliation_basic(
    manager: ExternalResourcesManager,
    reconciliation: Reconciliation,
    state: ExternalResourceState,
    action: Action,
    status: ResourceStatus,
    expected: bool,
) -> None:
    reconciliation_ = reconciliation.dict()
    reconciliation_["action"] = action
    new_reconciliation = Reconciliation.parse_obj(reconciliation_)
    state.resource_status = status
    result = manager._resource_needs_reconciliation(new_reconciliation, state)
    assert result is expected


@pytest.mark.parametrize(
    "ts,expected",
    [
        (datetime(2024, 1, 1, 12, 30, 0), True),
        (datetime.now(), False),
    ],
)
def test_resource_needs_reconciliation_drift(
    manager: ExternalResourcesManager,
    reconciliation: Reconciliation,
    state: ExternalResourceState,
    ts: datetime,
    expected: bool,
) -> None:
    state.resource_status = ResourceStatus.CREATED
    state.ts = ts
    result = manager._resource_needs_reconciliation(reconciliation, state)
    assert result is expected


@pytest.mark.parametrize(
    ("resource_status", "action", "reconcile_status", "expected_status"),
    [
        (
            ResourceStatus.IN_PROGRESS,
            Action.APPLY,
            ReconcileStatus.SUCCESS,
            ResourceStatus.PENDING_SECRET_SYNC,
        ),
        (
            ResourceStatus.IN_PROGRESS,
            Action.APPLY,
            ReconcileStatus.ERROR,
            ResourceStatus.ERROR,
        ),
        (
            ResourceStatus.IN_PROGRESS,
            Action.APPLY,
            ReconcileStatus.NOT_EXISTS,
            ResourceStatus.ERROR,
        ),
        (
            ResourceStatus.DELETE_IN_PROGRESS,
            Action.DESTROY,
            ReconcileStatus.SUCCESS,
            ResourceStatus.DELETED,
        ),
        (
            ResourceStatus.DELETE_IN_PROGRESS,
            Action.DESTROY,
            ReconcileStatus.NOT_EXISTS,
            ResourceStatus.ERROR,
        ),
        (
            ResourceStatus.DELETE_IN_PROGRESS,
            Action.DESTROY,
            ReconcileStatus.ERROR,
            ResourceStatus.ERROR,
        ),
    ],
)
def test_get_reconciliation_status(
    manager: ExternalResourcesManager,
    reconciliation: Reconciliation,
    state: ExternalResourceState,
    resource_status: ResourceStatus,
    action: Action,
    reconcile_status: ReconcileStatus,
    expected_status: ResourceStatus,
) -> None:
    state.resource_status = resource_status
    r_dict = reconciliation.dict()
    r_dict["action"] = action
    r = Reconciliation.parse_obj(r_dict)
    manager.reconciler.get_resource_reconcile_status.return_value = reconcile_status  # type:ignore
    status = manager._get_reconciliation_status(r, state)
    assert status.resource_status == expected_status


@pytest.mark.parametrize(
    ("state_resource_status", "reconciliation_resource_status"),
    [
        (
            ResourceStatus.IN_PROGRESS,
            ResourceStatus.IN_PROGRESS,
        ),
        (
            ResourceStatus.IN_PROGRESS,
            ResourceStatus.DELETE_IN_PROGRESS,
        ),
        (
            ResourceStatus.DELETE_IN_PROGRESS,
            ResourceStatus.IN_PROGRESS,
        ),
        (
            ResourceStatus.DELETE_IN_PROGRESS,
            ResourceStatus.DELETE_IN_PROGRESS,
        ),
        (
            ResourceStatus.NOT_EXISTS,
            ResourceStatus.IN_PROGRESS,
        ),
    ],
)
def test_update_resource_state_does_nothing(
    manager: ExternalResourcesManager,
    reconciliation: Reconciliation,
    reconciliation_status: ReconciliationStatus,
    state: ExternalResourceState,
    state_resource_status: ResourceStatus,
    reconciliation_resource_status: ResourceStatus,
) -> None:
    state.resource_status = state_resource_status
    reconciliation_status.resource_status = reconciliation_resource_status
    manager._update_resource_state(reconciliation, state, reconciliation_status)
    manager.state_mgr = cast(Mock, manager.state_mgr)
    manager.state_mgr.del_external_resource_state.assert_not_called()
    manager.state_mgr.set_external_resource_state.assert_not_called()


@pytest.mark.parametrize(
    ("state_resource_status", "reconcile_resource_status"),
    [
        (ResourceStatus.NOT_EXISTS, ResourceStatus.CREATED),
        (ResourceStatus.NOT_EXISTS, ResourceStatus.ERROR),
        (ResourceStatus.NOT_EXISTS, ResourceStatus.PENDING_SECRET_SYNC),
        (ResourceStatus.IN_PROGRESS, ResourceStatus.CREATED),
        (ResourceStatus.IN_PROGRESS, ResourceStatus.ERROR),
        (ResourceStatus.IN_PROGRESS, ResourceStatus.PENDING_SECRET_SYNC),
    ],
)
def test_update_resource_state_updates_state(
    manager: ExternalResourcesManager,
    reconciliation: Reconciliation,
    reconciliation_status: ReconciliationStatus,
    state: ExternalResourceState,
    state_resource_status: ResourceStatus,
    reconcile_resource_status: ResourceStatus,
) -> None:
    state.resource_status = state_resource_status
    reconciliation_status.resource_status = reconcile_resource_status
    manager._update_resource_state(reconciliation, state, reconciliation_status)
    manager.state_mgr = cast(Mock, manager.state_mgr)
    manager.state_mgr.del_external_resource_state.assert_not_called()
    manager.state_mgr.set_external_resource_state.assert_called_once()


@pytest.mark.parametrize(
    ("state_resource_status", "reconcile_resource_status"),
    [
        (ResourceStatus.IN_PROGRESS, ResourceStatus.DELETED),
        (ResourceStatus.DELETE_IN_PROGRESS, ResourceStatus.DELETED),
    ],
)
def test_update_resource_state_deletes_state(
    manager: ExternalResourcesManager,
    reconciliation: Reconciliation,
    reconciliation_status: ReconciliationStatus,
    state: ExternalResourceState,
    state_resource_status: ResourceStatus,
    reconcile_resource_status: ResourceStatus,
) -> None:
    state.resource_status = state_resource_status
    reconciliation_status.resource_status = reconcile_resource_status
    manager._update_resource_state(reconciliation, state, reconciliation_status)
    manager.state_mgr = cast(Mock, manager.state_mgr)
    manager.state_mgr.del_external_resource_state.assert_called_once()
    manager.state_mgr.set_external_resource_state.assert_not_called()
