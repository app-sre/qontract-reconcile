import reconcile.terraform_resources as integ
from reconcile.utils.terraform_resource_spec import (
    TerraformResourceUniqueKey,
    TerraformResourceSpec,
)


def test_filter_namespaces_no_managed_tf_resources():
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": False,
        "terraformResources": [],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedTerraformResources": True,
        "terraformResources": [ra],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == [ns2]


def test_filter_namespaces_with_account_filter():
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    rb = {"account": "b", "identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": True,
        "terraformResources": [ra],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedTerraformResources": True,
        "terraformResources": [rb],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, "a")
    assert filtered == [ns1]


def test_filter_namespaces_no_account_filter():
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    rb = {"account": "b", "identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": True,
        "terraformResources": [ra],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedTerraformResources": True,
        "terraformResources": [rb],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == namespaces


def test_filter_namespaces_no_tf_resources_no_account_filter():
    """
    this test makes sure that a namespace is returned even if it has no resources
    attached. this way we can delete the last terraform resources that might have been
    defined on the namespace previously
    """
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": True,
        "terraformResources": [],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedTerraformResources": True,
        "terraformResources": [ra],
        "cluster": {"name": "c"},
    }

    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == [ns1, ns2]


def test_filter_tf_namespaces_no_tf_resources_with_account_filter():
    """
    even if an account filter is defined, a namespace without resources is returned
    to enable terraform resource deletion. in contrast to that, a namespace with a resource
    that does not match the account will not be returned.
    """
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": True,
        "terraformResources": [],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedTerraformResources": True,
        "terraformResources": [ra],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, "b")
    assert filtered == [ns1]


def test_tf_disabled_namespace_with_resources():
    """
    even if a namespace has tf resources, they are not considered when the
    namespace is not enabled for tf resource management
    """
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": False,
        "terraformResources": [ra],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    resources = integ.init_tf_resource_specs(namespaces, None)
    assert not resources


def test_resource_specs_without_account_filter():
    """
    if no account filter is given, all resources of namespaces with
    enabled tf resource management are expected to be returned
    """
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": True,
        "terraformResources": [ra],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    resources = integ.init_tf_resource_specs(namespaces, None)
    assert resources == {
        TerraformResourceUniqueKey.from_dict(ra): TerraformResourceSpec(ra, ns1)
    }


def test_resource_specs_with_account_filter():
    """
    if an account filter is given only the resources defined for
    that account are expected
    """
    ra = {"account": "a", "identifier": "a", "provider": "p"}
    rb = {"account": "b", "identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedTerraformResources": True,
        "terraformResources": [ra, rb],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    resources = integ.init_tf_resource_specs(namespaces, "a")
    assert resources == {
        TerraformResourceUniqueKey.from_dict(ra): TerraformResourceSpec(ra, ns1)
    }
