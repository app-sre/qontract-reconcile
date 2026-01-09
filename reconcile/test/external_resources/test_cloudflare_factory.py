from unittest.mock import Mock

import pytest

from reconcile.external_resources.cloudflare import (
    CloudflareDefaultResourceFactory,
    CloudflareResourceFactory,
    CloudflareZoneFactory,
)
from reconcile.external_resources.factories import (
    CloudflareExternalResourceFactory,
    ModuleProvisionDataFactory,
    ObjectFactory,
    TerraformModuleProvisionDataFactory,
)
from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceModuleConfiguration,
    ExternalResourceModuleKey,
    ExternalResourceProvision,
    ExternalResourcesInventory,
    ModuleInventory,
    TerraformModuleProvisionData,
)
from reconcile.gql_definitions.external_resources.external_resources_modules import (
    ExternalResourcesChannelV1,
    ExternalResourcesModuleV1,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.json import json_dumps


@pytest.fixture
def cloudflare_module() -> ExternalResourcesModuleV1:
    return ExternalResourcesModuleV1(
        module_type="terraform",
        provision_provider="cloudflare",
        provider="zone",
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
        ],
        default_channel="stable",
    )


@pytest.fixture
def cloudflare_module_inventory(
    cloudflare_module: ExternalResourcesModuleV1,
) -> ModuleInventory:
    key = ExternalResourceModuleKey(
        provision_provider=cloudflare_module.provision_provider,
        provider=cloudflare_module.provider,
    )
    return ModuleInventory({key: cloudflare_module})


def test_create_cloudflare_external_resource(
    secret_reader: Mock,
    settings: ExternalResourcesSettingsV1,
    cloudflare_module_inventory: ModuleInventory,
) -> None:
    tf_factory = TerraformModuleProvisionDataFactory(settings=settings)
    er_inventory = ExternalResourcesInventory([])
    factory = CloudflareExternalResourceFactory(
        module_inventory=cloudflare_module_inventory,
        er_inventory=er_inventory,
        secret_reader=secret_reader,
        provision_factories=ObjectFactory[ModuleProvisionDataFactory](
            factories={"terraform": tf_factory}
        ),
        resource_factories=ObjectFactory[CloudflareResourceFactory](
            factories={},
            default_factory=CloudflareDefaultResourceFactory(
                er_inventory, secret_reader
            ),
        ),
    )
    account_id = "test-account-id"
    secret_reader.read_all.return_value = {
        "account_id": account_id,
    }
    spec = ExternalResourceSpec(
        provision_provider="cloudflare",
        provisioner={
            "name": "test-cf-account",
            "api_credentials": {
                "path": "path/to/cf/credentials",
                "field": "all",
                "version": 1,
            },
        },
        resource={
            "identifier": "test-zone",
            "provider": "zone",
            "zone": "example.com",
        },
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
            "identifier": "test-zone",
            "zone": "example.com",
            "account_id": account_id,
        },
        provision=ExternalResourceProvision(
            provision_provider="cloudflare",
            provisioner="test-cf-account",
            provider="zone",
            identifier="test-zone",
            target_cluster="test_cluster",
            target_namespace="test_namespace",
            target_secret_name="test-zone-zone",
            module_provision_data=TerraformModuleProvisionData(
                tf_state_bucket=settings.tf_state_bucket,
                tf_state_region=settings.tf_state_region,
                tf_state_dynamodb_table=settings.tf_state_dynamodb_table,
                tf_state_key="cloudflare/test-cf-account/zone/test-zone/terraform.tfstate",
            ),
        ),
    )


def test_create_cloudflare_zone_external_resource(
    secret_reader: Mock,
    settings: ExternalResourcesSettingsV1,
    cloudflare_module_inventory: ModuleInventory,
) -> None:
    tf_factory = TerraformModuleProvisionDataFactory(settings=settings)
    er_inventory = ExternalResourcesInventory([])
    factory = CloudflareExternalResourceFactory(
        module_inventory=cloudflare_module_inventory,
        er_inventory=er_inventory,
        secret_reader=secret_reader,
        provision_factories=ObjectFactory[ModuleProvisionDataFactory](
            factories={"terraform": tf_factory}
        ),
        resource_factories=ObjectFactory[CloudflareResourceFactory](
            factories={
                "zone": CloudflareZoneFactory(er_inventory, secret_reader),
            },
            default_factory=CloudflareDefaultResourceFactory(
                er_inventory, secret_reader
            ),
        ),
    )
    account_id = "test-account-id"
    secret_reader.read_all.return_value = {
        "account_id": account_id,
    }
    action_parameters = {
        "from_value": {
            "target_url": {
                "value": "https://example.com/",
            },
            "status_code": 301,
            "preserve_query_string": True,
        }
    }
    spec = ExternalResourceSpec(
        provision_provider="cloudflare",
        provisioner={
            "name": "test-cf-account",
            "api_credentials": {
                "path": "path/to/cf/credentials",
                "field": "all",
                "version": 1,
            },
        },
        resource={
            "identifier": "test-zone",
            "provider": "zone",
            "zone": "example.com",
            "rulesets": [
                {
                    "identifier": "redirects",
                    "name": "redirects",
                    "kind": "zone",
                    "phase": "http_request_dynamic_redirect",
                    "description": "Redirects",
                    "rules": [
                        {
                            "ref": "redirect-www-to-root",
                            "expression": '(http.request.full_uri wildcard "http*://www.example.com/*")',
                            "action": "redirect",
                            "description": "redirect www to root",
                            "enabled": True,
                            "action_parameters": json_dumps(action_parameters),
                        }
                    ],
                }
            ],
        },
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
            "account_id": account_id,
            "identifier": "test-zone",
            "zone": "example.com",
            "rulesets": [
                {
                    "identifier": "redirects",
                    "name": "redirects",
                    "kind": "zone",
                    "phase": "http_request_dynamic_redirect",
                    "description": "Redirects",
                    "rules": [
                        {
                            "ref": "redirect-www-to-root",
                            "expression": '(http.request.full_uri wildcard "http*://www.example.com/*")',
                            "action": "redirect",
                            "description": "redirect www to root",
                            "enabled": True,
                            "action_parameters": action_parameters,
                        }
                    ],
                }
            ],
        },
        provision=ExternalResourceProvision(
            provision_provider="cloudflare",
            provisioner="test-cf-account",
            provider="zone",
            identifier="test-zone",
            target_cluster="test_cluster",
            target_namespace="test_namespace",
            target_secret_name="test-zone-zone",
            module_provision_data=TerraformModuleProvisionData(
                tf_state_bucket=settings.tf_state_bucket,
                tf_state_region=settings.tf_state_region,
                tf_state_dynamodb_table=settings.tf_state_dynamodb_table,
                tf_state_key="cloudflare/test-cf-account/zone/test-zone/terraform.tfstate",
            ),
        ),
    )
