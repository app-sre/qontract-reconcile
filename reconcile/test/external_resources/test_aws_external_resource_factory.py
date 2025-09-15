from typing import cast
from unittest.mock import Mock

from reconcile.external_resources.aws import (
    AWSDefaultResourceFactory,
    AWSRdsFactory,
    AWSResourceFactory,
)
from reconcile.external_resources.factories import (
    AWSExternalResourceFactory,
    ModuleProvisionDataFactory,
    ObjectFactory,
    TerraformModuleProvisionDataFactory,
)
from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceModuleConfiguration,
    ExternalResourceProvision,
    ExternalResourcesInventory,
    ModuleInventory,
    TerraformModuleProvisionData,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec


def test_create_external_resource(
    secret_reader: Mock,
    settings: ExternalResourcesSettingsV1,
    module_inventory: ModuleInventory,
) -> None:
    tf_factory = TerraformModuleProvisionDataFactory(settings=settings)
    er_inventory = ExternalResourcesInventory([])
    factory = AWSExternalResourceFactory(
        module_inventory=module_inventory,
        er_inventory=er_inventory,
        secret_reader=secret_reader,
        provision_factories=ObjectFactory[ModuleProvisionDataFactory](
            factories={"terraform": tf_factory, "cdktf": tf_factory}
        ),
        resource_factories=ObjectFactory[AWSResourceFactory](
            factories={
                "rds": AWSRdsFactory(er_inventory, secret_reader),
            },
            default_factory=AWSDefaultResourceFactory(er_inventory, secret_reader),
        ),
        default_tags=cast("dict[str, str]", settings.default_tags),
    )
    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test", "resources_default_region": "us-east-1"},
        resource={"identifier": "test-rds", "provider": "rds"},
        namespace={
            "cluster": {"name": "test_cluster"},
            "name": "test_namespace",
            "environment": {"name": "test_env"},
            "app": {
                "name": "test_app",
            },
        },
    )
    module_conf = ExternalResourceModuleConfiguration(
        image="stable-image",
        version="1.0.0",
        outputs_secret_image="path/to/er-output-secret-image",
        outputs_secret_version="er-output-secret-version",
        reconcile_timeout_minutes=60,
        reconcile_drift_interval_minutes=60,
    )

    result = factory.create_external_resource(
        spec=spec,
        module_conf=module_conf,
    )

    assert result == ExternalResource(
        data={
            "identifier": "test-rds",
            "output_prefix": "test-rds-rds",
            "timeouts": {"create": "55m", "update": "55m", "delete": "55m"},
            "tags": {
                "managed_by_integration": "external_resources",
                "cluster": "test_cluster",
                "namespace": "test_namespace",
                "environment": "test_env",
                "env": "test",
                "app": "test_app",
            },
            "region": "us-east-1",
        },
        provision=ExternalResourceProvision(
            provision_provider="aws",
            provisioner="test",
            provider="rds",
            identifier="test-rds",
            target_cluster="test_cluster",
            target_namespace="test_namespace",
            target_secret_name="test-rds-rds",
            module_provision_data=TerraformModuleProvisionData(
                tf_state_bucket=settings.tf_state_bucket,
                tf_state_region=settings.tf_state_region,
                tf_state_dynamodb_table=settings.tf_state_dynamodb_table,
                tf_state_key="aws/test/rds/test-rds/terraform.tfstate",
            ),
        ),
    )
