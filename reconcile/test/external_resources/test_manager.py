from collections.abc import Mapping
from datetime import datetime
from unittest.mock import Mock

import pytest
from pytest import fixture
from pytest_mock import MockerFixture

from reconcile.external_resources.manager import (
    ExternalResourcesJobImpl,
    ExternalResourcesManager,
    ReconcileStatus,
    ResourceStatus,
)
from reconcile.external_resources.model import (
    Action,
    ExternalResourceModule,
    ExternalResourceModuleKey,
    ExternalResourcesSettings,
    Reconciliation,
)
from reconcile.external_resources.state import (
    ExternalResourcesStateDynamoDB,
    ExternalResourceState,
)


@fixture
def settings() -> ExternalResourcesSettings:
    return ExternalResourcesSettings(
        tf_state_bucket="bucket",
        tf_state_region="us-east-1",
        tf_state_dynamodb_table="dynamodb_table",
        state_dynamodb_index="state_dynamo_index",
        state_dynamodb_table="state_dynamo_table",
    )


@fixture
def module() -> ExternalResourceModule:
    return ExternalResourceModule(
        image="image",
        default_version="0.0.1",
        provision_provider="aws",
        provider="aws-iam-role",
        reconcile_drift_interval_minutes=60,
        reconcile_timeout_minutes=60,
    )


@fixture
def modules(
    module: ExternalResourceModule,
) -> Mapping[ExternalResourceModuleKey, ExternalResourceModule]:
    key = ExternalResourceModuleKey(provision_provider="aws", provider="aws-iam-role")
    return {key: module}


@fixture
def manager(
    mocker: MockerFixture, settings: ExternalResourcesSettings, modules: Mapping
) -> ExternalResourcesManager:
    return ExternalResourcesManager(
        state_manager=Mock(spec=ExternalResourcesStateDynamoDB),
        oc=Mock(),
        cluster="cluster",
        namespace="namespace",
        settings=settings,
        modules=modules,
        impl=Mock(spec=ExternalResourcesJobImpl),
        dry_run=False,
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
    module: ExternalResourceModule,
    state: ExternalResourceState,
    action: Action,
    status: ResourceStatus,
    expected: bool,
) -> None:
    _reconciliation = reconciliation.dict()
    _reconciliation["action"] = action
    new_reconciliation = Reconciliation.parse_obj(_reconciliation)
    state.resource_status = status
    result = manager.resource_needs_reconciliation(new_reconciliation, module, state)
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
    module: ExternalResourceModule,
    state: ExternalResourceState,
    ts: datetime,
    expected: bool,
) -> None:
    state.resource_status = ResourceStatus.CREATED
    state.resource_digest = reconciliation.resource_digest
    state.ts = ts
    result = manager.resource_needs_reconciliation(reconciliation, module, state)
    assert result is expected


@pytest.mark.parametrize(
    "_resource_status,_action,_reconcile_status,_expected_status",
    [
        (
            ResourceStatus.IN_PROGRESS,
            Action.APPLY,
            ReconcileStatus.SUCCESS,
            ResourceStatus.CREATED,
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
def test_update_in_progress_state_status(
    manager: ExternalResourcesManager,
    reconciliation: Reconciliation,
    state: ExternalResourceState,
    _resource_status: ResourceStatus,
    _action: Action,
    _reconcile_status: ReconcileStatus,
    _expected_status: ResourceStatus,
) -> None:
    state.resource_status = _resource_status
    r_dict = reconciliation.dict()
    r_dict["action"] = _action
    _r = Reconciliation.parse_obj(r_dict)
    manager.impl.get_resource_reconcile_status.return_value = _reconcile_status  # type:ignore

    manager._update_in_progress_state(_r, state)
    assert state.resource_status == _expected_status
