from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any

import pytest
from pytest_mock import MockerFixture

import reconcile.terraform_resources as integ
from reconcile.gql_definitions.terraform_resources.terraform_resources_namespaces import (
    NamespaceV1,
)


def test_cannot_use_exclude_accounts_if_not_dry_run():
    with pytest.raises(integ.ExcludeAccountsAndDryRunException) as excinfo:
        integ.run(False, exclude_accounts=("a", "b"))

    assert "--exclude-accounts is only supported in dry-run mode" in str(excinfo.value)


def test_cannot_use_exclude_account_with_account_name():
    with pytest.raises(integ.ExcludeAccountsAndAccountNameException) as excinfo:
        integ.run(True, exclude_accounts=("a", "b"), account_name=("c", "d"))

    assert (
        "Using --exclude-accounts and --account-name at the same time is not allowed"
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

    filtered = integ.filter_accounts_by_name(accounts, filter=("a", "b"))

    assert filtered == [{"name": "a"}, {"name": "b"}]


def test_exclude_accounts_by_name():
    accounts = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    filtered = integ.exclude_accounts_by_name(accounts, filter=("a", "b"))

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


def test_empty_run(mocker: MockerFixture) -> None:
    mocked_queries = mocker.patch("reconcile.terraform_resources.queries")
    mocked_queries.get_aws_accounts.return_value = [{"name": "a"}]
    mocked_queries.get_app_interface_settings.return_value = []

    mocker.patch("reconcile.terraform_resources.get_namespaces").return_value = []

    mocked_ts = mocker.patch("reconcile.terraform_resources.Terrascript", autospec=True)
    mocked_ts.return_value.resource_spec_inventory = {}

    mocked_tf = mocker.patch("reconcile.terraform_resources.Terraform", autospec=True)
    mocked_tf.return_value.plan.return_value = (False, None)
    mocked_tf.return_value.should_apply = False

    mocker.patch("reconcile.terraform_resources.AWSApi", autospec=True)
    mocker.patch("reconcile.terraform_resources.sys")

    mocked_logging = mocker.patch("reconcile.terraform_resources.logging")

    integ.run(True, account_name="a")

    mocked_logging.warning.assert_called_once_with(
        "No terraform namespaces found, consider disabling this integration, account names: a"
    )
