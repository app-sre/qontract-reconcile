from collections.abc import Mapping
from datetime import datetime
from unittest.mock import Mock

import pytest
from pytest import fixture
from pytest_mock import MockerFixture

from reconcile.external_resources.manager import (
    ExternalResourcesManager,
    ReconcileStatus,
    ResourceStatus,
    setup_factories,
)
from reconcile.external_resources.model import (
    Action,
    ExternalResourceModuleKey,
    ExternalResourcesInventory,
    ModuleInventory,
    Reconciliation,
)
from reconcile.external_resources.reconciler import ExternalResourcesReconciler
from reconcile.external_resources.state import (
    ExternalResourcesStateDynamoDB,
    ExternalResourceState,
)
from reconcile.gql_definitions.external_resources.external_resources_modules import (
    ExternalResourcesModuleV1,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    AWSAccountV1,
    ClusterV1,
    ExternalResourcesSettingsV1,
    NamespaceV1,
)


@fixture
def settings() -> ExternalResourcesSettingsV1:
    return ExternalResourcesSettingsV1(
        tf_state_bucket="bucket",
        tf_state_region="us-east-1",
        tf_state_dynamodb_table="dynamodb_table",
        state_dynamodb_account=AWSAccountV1(name="app-int-example-01"),
        state_dynamodb_table="state_dynamo_table",
        state_dynamodb_region="us-east-1",
        workers_cluster=ClusterV1(name="appint-ex-01"),
        workers_namespace=NamespaceV1(name="external-resources-poc"),
        vault_secrets_path="app-sre/integration-outputs/external-resources",
    )


@fixture
def module() -> ExternalResourcesModuleV1:
    return ExternalResourcesModuleV1(
        image="image",
        module_type="cdktf",
        default_version="0.0.1",
        provision_provider="aws",
        provider="aws-iam-role",
        reconcile_drift_interval_minutes=60,
        reconcile_timeout_minutes=60,
        outputs_secret_sync=True,
    )


@fixture
def modules(
    module: ExternalResourcesModuleV1,
) -> Mapping[ExternalResourceModuleKey, ExternalResourcesModuleV1]:
    key = ExternalResourceModuleKey(provision_provider="aws", provider="aws-iam-role")
    return {key: module}


@fixture
def module_inventory(module: ExternalResourcesModuleV1) -> ModuleInventory:
    key = ExternalResourceModuleKey(
        provision_provider=module.provision_provider, provider=module.provider
    )
    return ModuleInventory({key: module})


@fixture
def manager(
    mocker: MockerFixture,
    settings: ExternalResourcesSettingsV1,
    module_inventory: ModuleInventory,
) -> ExternalResourcesManager:
    er_inventory = ExternalResourcesInventory([])
    secret_reader = Mock()
    reconciler = Mock(spec=ExternalResourcesReconciler)
    secrets_reconciler = Mock()
    factories = setup_factories(settings, module_inventory, er_inventory, secret_reader)

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
    _reconciliation = reconciliation.dict()
    _reconciliation["action"] = action
    new_reconciliation = Reconciliation.parse_obj(_reconciliation)
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
    "_resource_status,_action,_reconcile_status,_expected_status",
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
    manager.reconciler.get_resource_reconcile_status.return_value = _reconcile_status  # type:ignore

    manager._update_in_progress_state(_r, state)
    assert state.resource_status == _expected_status
