from unittest.mock import create_autospec, MagicMock

import pytest

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.terraform.config_client import (
    TerraformConfigClientCollection,
    TerraformConfigClient,
    ClientAlreadyRegisteredError,
    ClientNotRegisteredError,
)


def create_external_resource_spec(name):
    return ExternalResourceSpec(
        "cloudflare_zone",
        {"name": name, "automationToken": {}},
        {
            "provider": "cloudflare_zone",
            "identifier": f"{name}-com",
            "zone": "{name}.com",
            "plan": "enterprise",
            "type": "partial",
        },
        {},
    )


def test_terraform_config_client_collection_populate_resources():
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_2: MagicMock = create_autospec(TerraformConfigClient)
    client_3: MagicMock = create_autospec(TerraformConfigClient)

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("acct_1", client_1)
    terraform_configs.register_client("acct_2", client_2)
    terraform_configs.register_client("acct_3", client_3)

    terraform_configs.populate_resources()

    client_1.populate_resources.assert_called_once()
    client_2.populate_resources.assert_called_once()
    client_3.populate_resources.assert_called_once()


def test_terraform_config_client_collection_add_specs():
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_2: MagicMock = create_autospec(TerraformConfigClient)
    client_3: MagicMock = create_autospec(TerraformConfigClient)

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("acct_1", client_1)
    terraform_configs.register_client("acct_2", client_2)
    terraform_configs.register_client("acct_3", client_3)

    spec_1 = create_external_resource_spec("dev-1")
    spec_2 = create_external_resource_spec("dev-2")
    spec_3 = create_external_resource_spec("dev-3")
    spec_4 = create_external_resource_spec("dev-4")
    spec_5 = create_external_resource_spec("dev-5")

    terraform_configs.add_specs("acct_1", [spec_1])
    terraform_configs.add_specs("acct_2", [spec_2, spec_3])
    terraform_configs.add_specs("acct_3", [spec_4, spec_5])

    client_1.add_specs.assert_called_once_with([spec_1])
    client_2.add_specs.assert_called_once_with([spec_2, spec_3])
    client_3.add_specs.assert_called_once_with([spec_4, spec_5])


def test_terraform_config_client_collection_dump():
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_1.dump.return_value = {"acct_1": "/tmp/acct_1"}
    client_2: MagicMock = create_autospec(TerraformConfigClient)
    client_2.dump.return_value = {"acct_2": "/tmp/acct_2"}
    client_3: MagicMock = create_autospec(TerraformConfigClient)
    client_3.dump.return_value = {"acct_3": "/tmp/acct_3"}

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("acct_1", client_1)
    terraform_configs.register_client("acct_2", client_2)
    terraform_configs.register_client("acct_3", client_3)

    working_dirs = terraform_configs.dump()

    assert working_dirs == {
        "acct_1": {"acct_1": "/tmp/acct_1"},
        "acct_2": {"acct_2": "/tmp/acct_2"},
        "acct_3": {"acct_3": "/tmp/acct_3"},
    }


def test_terraform_config_client_collection_raise_on_duplicate():
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_2: MagicMock = create_autospec(TerraformConfigClient)

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("duplicate", client_1)

    with pytest.raises(ClientAlreadyRegisteredError):
        terraform_configs.register_client("duplicate", client_2)


def test_terraform_config_client_collection_raise_on_missing():
    terraform_configs = TerraformConfigClientCollection()
    spec_1 = create_external_resource_spec("dev-1")

    with pytest.raises(ClientNotRegisteredError):
        terraform_configs.add_specs("doesnt_exist", [spec_1])
