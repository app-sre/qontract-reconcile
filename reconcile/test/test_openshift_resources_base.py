from unittest import TestCase
from unittest.mock import patch
from reconcile.test.fixtures import Fixtures

from reconcile.openshift_resources_base import canonicalize_namespaces, ob


@patch.object(ob, "aggregate_shared_resources", autospec=True)
class TestCanonicalizeNamespaces(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Fixtures("namespaces")

    def setUp(self):
        self.namespaces = [self.fixture.get_anymarkup("openshift-resources-only.yml")]

    def test_secret(self, ob):
        ns, override = canonicalize_namespaces(self.namespaces, ["vault-secret"])
        self.assertEqual(
            (ns, override),
            (
                [
                    {
                        "name": "ns1",
                        "cluster": {"name": "cs1"},
                        "managedResourceTypes": ["Template"],
                        "openshiftResources": [
                            {
                                "provider": "vault-secret",
                                "path": "/secret/place.yml",
                            }
                        ],
                    }
                ],
                ["Secret"],
            ),
        )

    def test_route(self, ob):
        ns, override = canonicalize_namespaces(self.namespaces, ["route"])
        self.assertEqual(
            (ns, override),
            (
                [
                    {
                        "name": "ns1",
                        "cluster": {"name": "cs1"},
                        "managedResourceTypes": ["Template"],
                        "openshiftResources": [
                            {"provider": "route", "path": "/route/network.yml"}
                        ],
                    }
                ],
                ["Route"],
            ),
        )

    def test_no_overrides(self, ob):
        ns, override = canonicalize_namespaces(self.namespaces, ["resource"])
        self.assertEqual(
            (ns, override),
            (
                [
                    {
                        "name": "ns1",
                        "cluster": {"name": "cs1"},
                        "managedResourceTypes": ["Template"],
                        "openshiftResources": [
                            {"provider": "resource", "path": "/some/path.yml"}
                        ],
                    }
                ],
                None,
            ),
        )
