import subprocess
from pathlib import Path
from unittest.mock import create_autospec, MagicMock, call, mock_open

import pytest

from reconcile.utils.exceptions import PrintToFileInGitRepositoryError
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.terraform.config_client import (
    TerraformConfigClientCollection,
    TerraformConfigClient,
    ClientAlreadyRegisteredError,
    ClientNotRegisteredError,
)


@pytest.fixture
def empty_git_repo(tmp_path_factory) -> Path:
    temp_dir = tmp_path_factory.mktemp("empty-git-repo")
    subprocess.check_call(["git", "init", temp_dir])
    return temp_dir


def create_external_resource_spec(provisioner_name, identifier):
    return ExternalResourceSpec(
        "cloudflare_zone",
        {"name": provisioner_name, "automationToken": {}},
        {
            "provider": "cloudflare_zone",
            "identifier": f"{identifier}-com",
            "zone": f"{identifier}.com",
            "plan": "enterprise",
            "type": "partial",
        },
        {},
    )


def test_terraform_config_client_collection_populate_resources():
    """populate_resources() is called on all registered clients."""
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
    """add_specs() is called on the correct client."""
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_2: MagicMock = create_autospec(TerraformConfigClient)
    client_3: MagicMock = create_autospec(TerraformConfigClient)

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("acct_1", client_1)
    terraform_configs.register_client("acct_2", client_2)
    terraform_configs.register_client("acct_3", client_3)

    spec_1 = create_external_resource_spec("acct_1", "dev-1")
    spec_2 = create_external_resource_spec("acct_2", "dev-2")
    spec_3 = create_external_resource_spec("acct_2", "dev-3")
    spec_4 = create_external_resource_spec("acct_3", "dev-4")
    spec_5 = create_external_resource_spec("acct_3", "dev-5")

    terraform_configs.add_specs([spec_1, spec_2, spec_3, spec_4, spec_5])

    client_1.add_spec.assert_called_once_with(spec_1)
    client_2.add_spec.assert_has_calls([call(spec_2), call(spec_3)])
    client_3.add_spec.assert_has_calls([call(spec_4), call(spec_5)])


def test_terraform_config_client_collection_add_specs_with_filter():
    """add_specs() is called on the correct client when a filter is set."""
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_2: MagicMock = create_autospec(TerraformConfigClient)
    client_3: MagicMock = create_autospec(TerraformConfigClient)

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("acct_1", client_1)
    terraform_configs.register_client("acct_2", client_2)
    terraform_configs.register_client("acct_3", client_3)

    spec_1 = create_external_resource_spec("acct_1", "dev-1")
    spec_2 = create_external_resource_spec("acct_2", "dev-2")
    spec_3 = create_external_resource_spec("acct_2", "dev-3")
    spec_4 = create_external_resource_spec("acct_3", "dev-4")
    spec_5 = create_external_resource_spec("acct_3", "dev-5")

    specs = [spec_1, spec_2, spec_3, spec_4, spec_5]
    # With the filter set, only a single client should have specs added.
    terraform_configs.add_specs(specs, account_filter="acct_3")

    client_1.add_spec.assert_not_called()
    client_2.add_spec.assert_not_called()
    client_3.add_spec.assert_has_calls([call(spec_4), call(spec_5)])


def test_terraform_config_client_collection_dump():
    """The working directories return by clients are aggregated properly in dump()."""
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


def test_terraform_config_client_collection_print_to_file(mocker):
    """
    The print_to_file kwarg results in a properly formatted file at the desired file
    path.
    """
    mock_builtins_open = mock_open()
    mocker.patch("builtins.open", mock_builtins_open)

    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_1.dumps.return_value = {"acct_1": "data"}
    client_2: MagicMock = create_autospec(TerraformConfigClient)
    client_2.dumps.return_value = {"acct_2": "data"}
    client_3: MagicMock = create_autospec(TerraformConfigClient)
    client_3.dumps.return_value = {"acct_3": "data"}

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("acct_1", client_1)
    terraform_configs.register_client("acct_2", client_2)
    terraform_configs.register_client("acct_3", client_3)

    # This file is never actually written to because of the patched builtins.open()
    terraform_configs.dump(print_to_file="/tmp/test-utils-terraform-config-client")

    comment_calls = [
        call("##### acct_1 #####\n"),
        call("##### acct_2 #####\n"),
        call("##### acct_3 #####\n"),
    ]

    data_calls = [
        call({"acct_1": "data"}),
        call({"acct_2": "data"}),
        call({"acct_3": "data"}),
    ]

    for comment in comment_calls:
        assert comment in mock_builtins_open.return_value.write.call_args_list

    for data in data_calls:
        assert data in mock_builtins_open.return_value.write.call_args_list


def test_terraform_config_client_collection_dump_print_file_git(empty_git_repo):
    """Using print_to_file in a git repo should result in an exception."""
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_1.dump.return_value = {"acct_1": "/tmp/acct_1"}

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("acct_1", client_1)

    with pytest.raises(PrintToFileInGitRepositoryError):
        terraform_configs.dump(
            print_to_file=f"{empty_git_repo}/terraform-config-print-to-file"
        )


def test_terraform_config_client_collection_raise_on_duplicate():
    """Client names must be unique."""
    client_1: MagicMock = create_autospec(TerraformConfigClient)
    client_2: MagicMock = create_autospec(TerraformConfigClient)

    terraform_configs = TerraformConfigClientCollection()
    terraform_configs.register_client("duplicate", client_1)

    with pytest.raises(ClientAlreadyRegisteredError):
        terraform_configs.register_client("duplicate", client_2)


def test_terraform_config_client_collection_raise_on_missing():
    """Specs cannot be added to clients that don't exist."""
    terraform_configs = TerraformConfigClientCollection()
    spec_1 = create_external_resource_spec("acct_1", "dev-1")

    with pytest.raises(ClientNotRegisteredError):
        terraform_configs.add_specs([spec_1])
