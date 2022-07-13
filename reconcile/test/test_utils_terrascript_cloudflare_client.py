import json
from unittest.mock import create_autospec, mock_open

import pytest
from terrascript import Terrascript

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


def test_create_cloudflare_resources_terraform_json(account_config, backend_config):
    """
    This test intentionally crosses many boundaries to cover most of the functionality
    from starting with an external resource spec definition to Terraform JSON config.
    The Terraform JSON config was generated by the code initially and tested with a
    `terraform plan`. This serves as a snapshot to ensure that there are not major
    changes in this functionality over time.
    """

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

    cloudflare_client.add_spec(spec)
    cloudflare_client.populate_resources()

    expected_dict = {
        "terraform": {
            "required_providers": {
                "cloudflare": {"source": "cloudflare/cloudflare", "version": "3.18"}
            },
            "backend": {
                "s3": {
                    "access_key": "access-key",
                    "secret_key": "secret-key",
                    "bucket": "bucket-name",
                    "key": "qontract-reconcile.tfstate",
                    "region": "us-east-1",
                }
            },
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


def test_terrascript_cloudflare_client_dump(mocker):
    """
    Tests that dump() properly calls the Python filesystem implementations to write to
    disk.
    """
    mock_builtins_open = mock_open()
    mocker.patch("builtins.open", mock_builtins_open)

    patch_mkdtemp = mocker.patch("tempfile.mkdtemp")
    patch_mkdtemp.return_value = "/tmp/test"

    mock_terrascript = create_autospec(Terrascript)
    mock_terrascript.__str__.return_value = "some data"

    cloudflare_client = TerrascriptCloudflareClient(mock_terrascript)
    cloudflare_client.dump()

    patch_mkdtemp.assert_called_once()
    mock_builtins_open.assert_called_once_with("/tmp/test/config.tf.json", "w")
    mock_builtins_open.return_value.write.assert_called_once_with("some data")


def test_terrascript_cloudflare_client_dump_existing_dir(mocker):
    """
    Tests that dump() properly calls the Python filesystem implementations to write to
    disk when an existing_dir is specified.
    """
    mock_builtins_open = mock_open()
    mocker.patch("builtins.open", mock_builtins_open)

    patch_mkdtemp = mocker.patch("tempfile.mkdtemp")
    patch_mkdtemp.return_value = "/tmp/test"

    mock_terrascript = create_autospec(Terrascript)
    mock_terrascript.__str__.return_value = "some data"

    cloudflare_client = TerrascriptCloudflareClient(mock_terrascript)
    cloudflare_client.dump(existing_dir="/tmp/existing-dir")

    patch_mkdtemp.assert_not_called()
    mock_builtins_open.assert_called_once_with("/tmp/existing-dir/config.tf.json", "w")
    mock_builtins_open.return_value.write.assert_called_once_with("some data")


def test_create_cloudflare_terrascript(account_config, backend_config):
    """Simple test to ensure that the Terrascript object is initialized."""
    ts = create_cloudflare_terrascript(account_config, backend_config, "3.18")

    assert isinstance(ts, Terrascript)
