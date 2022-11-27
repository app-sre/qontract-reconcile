import reconcile.terraform_resources as integ


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


def test_filter_tf_namespaces_namespace_deleted():
    """
    test that a deleted namespace is not returned
    """
    ra = {"identifier": "a", "provider": "p"}
    rb = {"identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
        "cluster": {"name": "c"},
        "delete": True,
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
    assert filtered == [ns2]
