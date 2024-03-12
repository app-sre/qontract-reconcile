from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from pytest_mock import MockerFixture

import reconcile.terraform_resources as integ
from reconcile.gql_definitions.terraform_resources.terraform_resources_namespaces import (
    NamespaceV1,
)
from reconcile.utils.secret_reader import SecretReaderBase


def test_cannot_use_exclude_accounts_if_not_dry_run():
    with pytest.raises(integ.ExcludeAccountsAndDryRunException) as excinfo:
        integ.run(False, exclude_accounts=("a", "b"))

    assert "--exclude-accounts is only supported in dry-run mode" in str(excinfo.value)


def test_cannot_use_exclude_account_with_same_account_name():
    with pytest.raises(integ.ExcludeAccountsAndAccountNameException) as excinfo:
        integ.run(True, exclude_accounts=("a", "b"), account_name=("b", "c", "d"))

    assert (
        "Using --exclude-accounts and --account-name with the same account is not allowed"
        in str(excinfo.value)
    )


def test_cannot_exclude_invalid_aws_account(mocker):
    mocker.patch(
        "reconcile.queries.get_aws_accounts",
        return_value=[{"name": "a"}],
        autospec=True,
    )
    with pytest.raises(ValueError) as excinfo:
        integ.run(True, exclude_accounts=("b"))

    assert (
        "Accounts {'b'} were provided as arguments, but not found in app-interface. Check your input for typos or for missing AWS account definitions."
        in str(excinfo.value)
    )


def test_cannot_exclude_all_accounts(mocker):
    mocker.patch(
        "reconcile.queries.get_aws_accounts",
        return_value=[{"name": "a"}, {"name": "b"}],
        autospec=True,
    )

    with pytest.raises(ValueError) as excinfo:
        integ.run(True, exclude_accounts=("a", "b"))

    assert "You have excluded all aws accounts, verify your input" in str(excinfo.value)


def test_cannot_pass_two_aws_account_if_not_dry_run():
    with pytest.raises(integ.MultipleAccountNamesInDryRunException) as excinfo:
        integ.run(False, account_name=("a", "b"))

    assert "Running with multiple accounts is only supported in dry-run mode" in str(
        excinfo.value
    )


def test_filter_accounts_by_name():
    accounts = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    filtered = integ.filter_accounts_by_name(accounts, names=("a", "b"))

    assert filtered == [{"name": "a"}, {"name": "b"}]


def test_exclude_accounts_by_name():
    accounts = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    filtered = integ.exclude_accounts_by_name(accounts, names=("a", "b"))

    assert filtered == [{"name": "c"}]


def test_cannot_pass_invalid_aws_account(mocker):
    mocker.patch(
        "reconcile.queries.get_aws_accounts",
        return_value=[{"name": "a"}],
        autospec=True,
    )
    with pytest.raises(ValueError) as excinfo:
        integ.run(True, account_name=("a", "b"))

    assert (
        "Accounts {'b'} were provided as arguments, but not found in app-interface. Check your input for typos or for missing AWS account definitions."
        in str(excinfo.value)
    )


def namespace_dict(
    name: str,
    external_resources: Iterable[Mapping[str, Any]],
    managed: bool = True,
    delete: bool = False,
) -> dict[str, Any]:
    data = {
        "name": name,
        "managedExternalResources": managed,
        "externalResources": external_resources,
        "cluster": {"name": "c", "serverUrl": "test"},
        "app": {"name": "test"},
        "environment": {"name": "test"},
    }
    if delete:
        data["delete"] = True
    return data


def test_filter_namespaces_no_managed_tf_resources(gql_class_factory: Callable):
    ra = {"identifier": "a", "provider": "p"}
    ns1 = gql_class_factory(NamespaceV1, namespace_dict("ns1", [], managed=False))
    ns2 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns2",
            [{"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}],
        ),
    )
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == [ns2]


def test_filter_namespaces_with_accounts_filter(gql_class_factory: Callable):
    ra = {"identifier": "a", "provider": "p"}
    rb = {"identifier": "b", "provider": "p"}
    rc = {"identifier": "c", "provider": "p"}
    ns1 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns1",
            [{"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}],
        ),
    )
    ns2 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns2",
            [{"provider": "aws", "provisioner": {"name": "b"}, "resources": [rb]}],
        ),
    )
    ns3 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns3",
            [{"provider": "aws", "provisioner": {"name": "c"}, "resources": [rc]}],
        ),
    )

    namespaces = [ns1, ns2, ns3]
    filtered = integ.filter_tf_namespaces(namespaces, ("a", "b"))
    assert filtered == [ns1, ns2]


def test_filter_namespaces_no_accounts_filter(gql_class_factory: Callable):
    ra = {"identifier": "a", "provider": "p"}
    rb = {"identifier": "b", "provider": "p"}
    ns1 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns1",
            [{"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}],
        ),
    )
    ns2 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns2",
            [{"provider": "aws", "provisioner": {"name": "b"}, "resources": [rb]}],
        ),
    )
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == namespaces


def test_filter_namespaces_no_tf_resources_no_accounts_filter(
    gql_class_factory: Callable,
):
    """
    this test makes sure that a namespace is returned even if it has no resources
    attached. this way we can delete the last terraform resources that might have been
    defined on the namespace previously
    """
    ra = {"identifier": "a", "provider": "p"}
    ns1 = gql_class_factory(NamespaceV1, namespace_dict("ns1", [], managed=True))
    ns2 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns2",
            [{"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}],
        ),
    )

    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == [ns1, ns2]


def test_filter_tf_namespaces_no_tf_resources_with_accounts_filter(
    gql_class_factory: Callable,
):
    """
    even if an account filter is defined, a namespace without resources is returned
    to enable terraform resource deletion. in contrast to that, a namespace with a resource
    that does not match the account will not be returned.
    """
    ra = {"identifier": "a", "provider": "p"}
    ns1 = gql_class_factory(NamespaceV1, namespace_dict("ns1", [], managed=True))
    ns2 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns2",
            [{"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}],
        ),
    )
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, ["b"])
    assert filtered == [ns1]


def test_filter_tf_namespaces_namespace_deleted(gql_class_factory: Callable):
    """
    test that a deleted namespace is not returned
    """
    ra = {"identifier": "a", "provider": "p"}
    rb = {"identifier": "b", "provider": "p"}
    ns1 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns1",
            [{"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}],
            delete=True,
        ),
    )
    ns2 = gql_class_factory(
        NamespaceV1,
        namespace_dict(
            "ns1",
            [{"provider": "aws", "provisioner": {"name": "b"}, "resources": [rb]}],
        ),
    )

    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == [ns2]


def setup_mocks(
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
    aws_accounts: list[dict[str, Any]],
    tf_namespaces: list[NamespaceV1],
    feature_toggle_state: bool = True,
) -> dict[str, Any]:
    mocked_queries = mocker.patch("reconcile.terraform_resources.queries")
    mocked_queries.get_aws_accounts.return_value = aws_accounts
    mocked_queries.get_app_interface_settings.return_value = []

    mocker.patch(
        "reconcile.terraform_resources.get_namespaces"
    ).return_value = tf_namespaces

    mocked_ts = mocker.patch(
        "reconcile.terraform_resources.Terrascript", autospec=True
    ).return_value
    mocked_ts.resource_spec_inventory = {}

    mocked_tf = mocker.patch(
        "reconcile.terraform_resources.Terraform", autospec=True
    ).return_value
    mocked_tf.plan.return_value = (False, None)
    mocked_tf.should_apply.return_value = False

    mocker.patch("reconcile.terraform_resources.AWSApi", autospec=True)

    mocked_logging = mocker.patch("reconcile.terraform_resources.logging")

    mocker.patch("reconcile.terraform_resources.get_app_interface_vault_settings")

    mocker.patch(
        "reconcile.terraform_resources.create_secret_reader",
        return_value=secret_reader,
    )

    mock_extended_early_exit_run = mocker.patch(
        "reconcile.terraform_resources.extended_early_exit_run"
    )

    get_feature_toggle_state = mocker.patch(
        "reconcile.terraform_resources.get_feature_toggle_state",
        return_value=feature_toggle_state,
    )

    return {
        "queries": mocked_queries,
        "ts": mocked_ts,
        "tf": mocked_tf,
        "logging": mocked_logging,
        "extended_early_exit_run": mock_extended_early_exit_run,
        "get_feature_toggle_state": get_feature_toggle_state,
    }


def test_empty_run(
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    mocks = setup_mocks(
        mocker,
        secret_reader,
        aws_accounts=[{"name": "a"}],
        tf_namespaces=[],
    )

    integ.run(True, account_name="a")

    mocks["logging"].warning.assert_called_once_with(
        "No terraform namespaces found, consider disabling this integration, account names: a"
    )


def test_run_with_extended_early_exit_run_enabled(
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    mocks = setup_mocks(
        mocker,
        secret_reader,
        aws_accounts=[{"name": "a"}],
        tf_namespaces=[],
    )
    defer = MagicMock()
    expected_runner_params = integ.RunnerParams(
        accounts=[{"name": "a"}],
        account_names={"a"},
        tf_namespaces=[],
        tf=mocks["tf"],
        ts=mocks["ts"],
        secret_reader=secret_reader,
        dry_run=True,
        enable_deletion=False,
        thread_pool_size=10,
        internal=None,
        use_jump_host=True,
        light=False,
        vault_output_path="",
        defer=defer,
    )

    integ.run.__wrapped__(
        True,
        account_name="a",
        enable_extended_early_exit=True,
        extended_early_exit_cache_ttl_seconds=60,
        log_cached_log_output=True,
        defer=defer,
    )
    expected_cache_source = {
        "terraform_configurations": mocks["ts"].terraform_configurations.return_value,
        "resource_spec_inventory": mocks["ts"].resource_spec_inventory,
    }

    mocks["extended_early_exit_run"].assert_called_once_with(
        integration=integ.QONTRACT_INTEGRATION,
        integration_version=integ.QONTRACT_INTEGRATION_VERSION,
        dry_run=True,
        cache_source=expected_cache_source,
        shard="a",
        ttl_seconds=60,
        logger=mocks["logging"].getLogger.return_value,
        runner=integ.runner,
        runner_params=expected_runner_params,
        secret_reader=secret_reader,
        log_cached_log_output=True,
    )


def test_run_with_extended_early_exit_run_disabled(
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    mocks = setup_mocks(
        mocker,
        secret_reader,
        aws_accounts=[{"name": "a"}],
        tf_namespaces=[],
    )

    integ.run(
        True,
        account_name="a",
        enable_extended_early_exit=False,
    )

    mocks["extended_early_exit_run"].assert_not_called()
    mocks["tf"].plan.assert_called_once_with(False)


def test_run_with_extended_early_exit_run_feature_disabled(
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    mocks = setup_mocks(
        mocker,
        secret_reader,
        aws_accounts=[{"name": "a"}],
        tf_namespaces=[],
        feature_toggle_state=False,
    )

    integ.run(
        True,
        account_name="a",
        enable_extended_early_exit=True,
    )

    mocks["extended_early_exit_run"].assert_not_called()
    mocks["tf"].plan.assert_called_once_with(False)
    mocks["get_feature_toggle_state"].assert_called_once_with(
        "terraform-resources-extended-early-exit",
        default=False,
    )


def test_terraform_resources_runner_dry_run(
    secret_reader: SecretReaderBase,
) -> None:
    tf = create_autospec(integ.Terraform)
    tf.plan.return_value = (False, None)

    ts = create_autospec(integ.Terrascript)
    terraform_configurations = {"a": "b"}
    ts.terraform_configurations.return_value = terraform_configurations

    defer = MagicMock()

    runner_params = dict(
        accounts=[{"name": "a"}],
        account_names={"a"},
        tf_namespaces=[],
        tf=tf,
        ts=ts,
        secret_reader=secret_reader,
        dry_run=True,
        enable_deletion=False,
        thread_pool_size=10,
        internal=None,
        use_jump_host=True,
        light=False,
        vault_output_path="",
        defer=defer,
    )

    result = integ.runner(**runner_params)

    assert result == integ.ExtendedEarlyExitRunnerResult(
        payload=terraform_configurations,
        applied_count=0,
    )


def test_terraform_resources_runner_no_dry_run(
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    tf = create_autospec(integ.Terraform)
    tf.plan.return_value = (False, None)
    tf.apply_count = 1
    tf.should_apply.return_value = True
    tf.apply.return_value = False

    ts = create_autospec(integ.Terrascript)
    terraform_configurations = {"a": "b"}
    ts.terraform_configurations.return_value = terraform_configurations
    ts.resource_spec_inventory = {}

    defer = MagicMock()

    mocked_ob = mocker.patch("reconcile.terraform_resources.ob")
    mocked_ob.realize_data.return_value = [{"action": "applied"}]

    runner_params = dict(
        accounts=[{"name": "a"}],
        account_names={"a"},
        tf_namespaces=[],
        tf=tf,
        ts=ts,
        secret_reader=secret_reader,
        dry_run=False,
        enable_deletion=False,
        thread_pool_size=10,
        internal=None,
        use_jump_host=True,
        light=False,
        vault_output_path="",
        defer=defer,
    )

    result = integ.runner(**runner_params)

    assert result == integ.ExtendedEarlyExitRunnerResult(
        payload=terraform_configurations,
        applied_count=2,
    )
