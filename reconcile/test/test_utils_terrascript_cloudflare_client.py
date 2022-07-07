import json

import pytest

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.terrascript.cloudflare_client import (
    CloudflareAccountConfig,
    TerrascriptCloudflareClient,
    create_cloudflare_terrascript,
)
from reconcile.utils.terraform.config import TerraformS3BackendConfig


@pytest.fixture
def account_config():
    return CloudflareAccountConfig(
        "account-name", "some@email", "api-token", "account-id"
    )


@pytest.fixture
def backend_config():
    return TerraformS3BackendConfig(
        "access-key",
        "secret-key",
        "bucket-name",
        "qontract-reconcile.tfstate",
        "us-east-1",
    )


def test_create_cloudflare_zone(account_config, backend_config):

    terrascript_client = create_cloudflare_terrascript(
        account_config, backend_config, "3.18"
    )

    cloudflare_client = TerrascriptCloudflareClient(terrascript_client)

    spec = ExternalResourceSpec(
        "cloudflare_zone",
        {"name": "dev", "automationToken": {}},
        {
            "provider": "cloudflare_zone",
            "identifier": "domain-com",
            "zone": "domain.com",
            "plan": "enterprise",
            "type": "partial",
        },
        {},
    )

    cloudflare_client.add_specs([spec])
    cloudflare_client.populate_resources()

    expected_dict = {
        "terraform": {
            "required_providers": {
                "cloudflare": {"source": "cloudflare/cloudflare", "version": "3.18"}
            }
        },
        "provider": {
            "cloudflare": [
                {
                    "email": "some@email",
                    "api_key": "api-token",
                    "account_id": "account-id",
                }
            ]
        },
        "resource": {
            "cloudflare_zone": {
                "domain-com": {
                    "zone": "domain.com",
                    "plan": "enterprise",
                    "type": "partial",
                }
            },
            "cloudflare_zone_settings_override": {
                "domain-com": {
                    "zone_id": "${cloudflare_zone.domain-com.id}",
                    "settings": {},
                    "depends_on": ["cloudflare_zone.domain-com"],
                }
            },
        },
    }

    assert json.loads(cloudflare_client.dumps()) == expected_dict
