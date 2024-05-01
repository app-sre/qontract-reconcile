from datetime import datetime

from pytest import fixture

from reconcile.external_resources.manager import ResourceStatus
from reconcile.external_resources.model import (
    Action,
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    Reconciliation,
)
from reconcile.external_resources.state import (
    ExternalResourceState,
)


@fixture
def key() -> ExternalResourceKey:
    return ExternalResourceKey(
        provision_provider="aws",
        provisioner_name="app-sre",
        provider="aws-iam-role",
        identifier="test-iam-role",
    )


@fixture
def reconciliation(key: ExternalResourceKey) -> Reconciliation:
    return Reconciliation(
        key=key,
        resource_hash="0000111100001111",
        input="INPUT",
        action=Action.APPLY,
        module_configuration=ExternalResourceModuleConfiguration(
            image="test-image",
            version="0.0.1",
            reconcile_drift_interval_minutes=120,
            reconcile_timeout_minutes=30,
        ),
    )


@fixture
def state(
    key: ExternalResourceKey, reconciliation: Reconciliation
) -> ExternalResourceState:
    return ExternalResourceState(
        key=key,
        ts=datetime(2024, 1, 1, 17, 14, 0),
        resource_status=ResourceStatus.NOT_EXISTS,
        reconciliation=reconciliation,
        reconciliation_errors=0,
    )
