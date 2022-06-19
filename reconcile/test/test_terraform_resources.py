import reconcile.terraform_resources as integ
from reconcile.utils.external_resource_spec import (
    ExternalResourceUniqueKey,
    ExternalResourceSpec,
)


def test_filter_namespaces_no_managed_tf_resources():
    ra = {"identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": False,
        "externalResources": [],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, None)
    assert filtered == [ns2]


def test_filter_namespaces_with_account_filter():
    ra = {"identifier": "a", "provider": "p"}
    rb = {"identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "b"}, "resources": [rb]}
        ],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1, ns2]
    filtered = integ.filter_tf_namespaces(namespaces, "a")
    assert filtered == [ns1]


def test_filter_namespaces_no_account_filter():
    ra = {"identifier": "a", "provider": "p"}
    rb = {"identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "b"}, "resources": [rb]}
        ],
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
    ra = {"identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
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
    ra = {"identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [],
        "cluster": {"name": "c"},
    }
    ns2 = {
        "name": "ns2",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
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
    ra = {"identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": False,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
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
    ra = {"identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    resources = integ.init_tf_resource_specs(namespaces, None)
    assert resources == {
        ExternalResourceUniqueKey.from_dict(ra): ExternalResourceSpec(ra, ns1)
    }


def test_resource_specs_with_account_filter():
    """
    if an account filter is given only the resources defined for
    that account are expected
    """
    ra = {"identifier": "a", "provider": "p"}
    rb = {"identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]},
            {"provider": "aws", "provisioner": {"name": "b"}, "resources": [rb]},
        ],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    resources = integ.init_tf_resource_specs(namespaces, "a")
    assert resources == {
        ExternalResourceUniqueKey.from_dict(ra): ExternalResourceSpec(ra, ns1)
    }
