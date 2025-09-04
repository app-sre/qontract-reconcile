from collections.abc import Mapping
from datetime import datetime

from pytest import fixture

from reconcile.external_resources.manager import ReconciliationStatus, ResourceStatus
from reconcile.external_resources.model import (
    Action,
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    ExternalResourceModuleKey,
    ModuleInventory,
    Reconciliation,
    Resources,
    ResourcesSpec,
)
from reconcile.external_resources.state import (
    ExternalResourceState,
)
from reconcile.gql_definitions.external_resources.external_resources_modules import (
    ExternalResourcesChannelV1,
    ExternalResourcesModuleV1,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    AWSAccountV1,
    ClusterV1,
    ExternalResourcesSettingsV1,
    NamespaceV1,
)
from reconcile.gql_definitions.fragments.deploy_resources import (
    DeployResourcesFields,
    ResourceLimitsRequirementsV1,
    ResourceRequestsRequirementsV1,
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
        module_default_resources=DeployResourcesFields(
            requests=ResourceRequestsRequirementsV1(cpu="100m", memory="128Mi"),
            limits=ResourceLimitsRequirementsV1(memory="4Gi", cpu=None),
        ),
        default_tags='{"env": "test"}',
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
            resources=Resources(
                requests=ResourcesSpec(cpu="100m", memory="128Mi"),
                limits=ResourcesSpec(memory="4Gi"),
            ),
        ),
    )


@fixture
def reconciliation_status() -> ReconciliationStatus:
    return ReconciliationStatus(
        reconcile_time=1, resource_status=ResourceStatus.CREATED
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
        module_type="cdktf",
        provision_provider="aws",
        provider="aws-iam-role",
        reconcile_drift_interval_minutes=60,
        reconcile_timeout_minutes=60,
        outputs_secret_sync=True,
        outputs_secret_image=None,
        outputs_secret_version=None,
        resources=None,
        channels=[
            ExternalResourcesChannelV1(
                name="stable", image="stable-image", version="1.0.0"
            ),
            ExternalResourcesChannelV1(
                name="candidate", image="candidate-image", version="2.0.0"
            ),
            ExternalResourcesChannelV1(
                name="experiment", image="experiment-image", version="3.0.0"
            ),
            ExternalResourcesChannelV1(
                name="experiment-2", image="experiment-2-image", version="4.0.0"
            ),
        ],
        default_channel="stable",
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
