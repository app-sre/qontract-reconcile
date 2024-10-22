from collections.abc import Mapping
from datetime import datetime

from pytest import fixture

from reconcile.external_resources.manager import ResourceStatus
from reconcile.external_resources.model import (
    Action,
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    ExternalResourceModuleKey,
    ModuleInventory,
    Reconciliation,
)
from reconcile.external_resources.state import (
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
        outputs_secret_image="path/to/er-output-secret-image",
        outputs_secret_version="er-output-secret-version",
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
            outputs_secret_image="path/to/er-output-secret-image",
            outputs_secret_version="er-output-secret-version",
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


@fixture
def module() -> ExternalResourcesModuleV1:
    return ExternalResourcesModuleV1(
        image="image",
        module_type="cdktf",
        version="0.0.1",
        provision_provider="aws",
        provider="aws-iam-role",
        reconcile_drift_interval_minutes=60,
        reconcile_timeout_minutes=60,
        outputs_secret_sync=True,
        outputs_secret_image=None,
        outputs_secret_version=None,
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
