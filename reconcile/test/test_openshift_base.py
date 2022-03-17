from typing import List, cast
import pytest

import testslide
import reconcile.openshift_base as sut
import reconcile.utils.openshift_resource as resource
from reconcile.test.fixtures import Fixtures
from reconcile.utils import oc

fxt = Fixtures("namespaces")


class TestInitSpecsToFetch(testslide.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.resource_inventory = cast(
            resource.ResourceInventory, testslide.StrictMock(resource.ResourceInventory)
        )

        self.oc_map = cast(oc.OC_Map, testslide.StrictMock(oc.OC_Map))
        self.mock_constructor(oc, "OC_Map").to_return_value(self.oc_map)
        self.namespaces = [fxt.get_anymarkup("valid-ns.yml")]

        self.mock_callable(
            self.resource_inventory, "initialize_resource_type"
        ).for_call("cs1", "ns1", "Template").to_return_value(None)

        self.mock_callable(self.oc_map, "get").for_call("cs1", False).to_return_value(
            "stuff"
        )
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)

    def test_only_cluster_or_namespace(self) -> None:
        with self.assertRaises(KeyError):
            sut.init_specs_to_fetch(
                self.resource_inventory,
                self.oc_map,
                [{"foo": "bar"}],
                [{"name": "cluster1"}],
            )

    def test_no_cluster_or_namespace(self) -> None:
        with self.assertRaises(KeyError):
            sut.init_specs_to_fetch(self.resource_inventory, self.oc_map)

    def assert_specs_match(
        self, result: List[sut.StateSpec], expected: List[sut.StateSpec]
    ) -> None:
        """Assert that two list of StateSpec are equal. Needed since StateSpec
        doesn't implement __eq__ and it's not worth to add for we will convert
        it to a dataclass when we move to Python 3.9"""
        self.assertEqual(
            [r.__dict__ for r in result],
            [e.__dict__ for e in expected],
        )

    def test_namespaces_managed(self) -> None:
        expected = [
            sut.StateSpec(
                type="current",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                resource="Template",
                resource_names=["tp1", "tp2"],
            ),
            sut.StateSpec(
                type="desired",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                resource={"provider": "resource", "path": "/some/path.yml"},
                parent=self.namespaces[0],
            ),
        ]

        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            self.oc_map,
            namespaces=self.namespaces,
        )
        self.assert_specs_match(rs, expected)

    def test_namespaces_managed_with_overrides(self) -> None:
        self.namespaces[0]["managedResourceTypeOverrides"] = [
            {"resource": "Template", "override": "something.template"}
        ]
        expected = [
            sut.StateSpec(
                type="current",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                resource="Template",
                resource_names=["tp1", "tp2"],
                resource_type_override="something.template",
            ),
            sut.StateSpec(
                type="desired",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                resource={"provider": "resource", "path": "/some/path.yml"},
                parent=self.namespaces[0],
            ),
        ]
        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            self.oc_map,
            namespaces=self.namespaces,
        )

        self.assert_specs_match(rs, expected)

    def test_namespaces_no_managedresourcenames(self) -> None:
        self.namespaces[0]["managedResourceNames"] = None
        self.namespaces[0]["managedResourceTypeOverrides"] = None
        self.maxDiff = None
        expected = [
            sut.StateSpec(
                type="current",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                parent=None,
                resource="Template",
                resource_names=None,
                resource_type_override=None,
            ),
            sut.StateSpec(
                type="desired",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                resource={"provider": "resource", "path": "/some/path.yml"},
                parent=self.namespaces[0],
            ),
        ]
        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            self.oc_map,
            namespaces=self.namespaces,
        )
        self.assert_specs_match(rs, expected)

    def test_namespaces_no_managedresourcetypes(self) -> None:
        self.namespaces[0]["managedResourceTypes"] = None
        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            self.oc_map,
            namespaces=self.namespaces,
        )

        self.assertEqual(rs, [])

    def test_namespaces_extra_managed_resource_name(self) -> None:
        self.namespaces[0]["managedResourceNames"].append(
            {
                "resource": "Secret",
                "resourceNames": ["s1", "s2"],
            },
        )

        with self.assertRaises(KeyError):
            sut.init_specs_to_fetch(
                self.resource_inventory,
                self.oc_map,
                namespaces=self.namespaces,
            )

    def test_namespaces_extra_override(self) -> None:
        self.namespaces[0]["managedResourceTypeOverrides"] = [
            {
                "resource": "Project",
                "override": "something.project",
            }
        ]

        with self.assertRaises(KeyError):
            sut.init_specs_to_fetch(
                self.resource_inventory, self.oc_map, namespaces=self.namespaces
            )

    def test_namespaces_override_managed_type(self) -> None:
        self.namespaces[0]["managedResourceTypeOverrides"] = [
            {
                "resource": "Project",
                "override": "wonderful.project",
            }
        ]

        expected = [
            sut.StateSpec(
                type="current",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                parent=None,
                resource="LimitRanges",
                resource_names=None,
                resource_type_override=None,
            ),
            sut.StateSpec(
                type="desired",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                resource={"provider": "resource", "path": "/some/path.yml"},
                parent=self.namespaces[0],
            ),
        ]

        self.maxDiff = None
        self.mock_callable(
            self.resource_inventory, "initialize_resource_type"
        ).for_call("cs1", "ns1", "LimitRanges").to_return_value(
            None
        ).and_assert_called_once()
        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            oc_map=self.oc_map,
            namespaces=self.namespaces,
            override_managed_types=["LimitRanges"],
        )
        self.assert_specs_match(rs, expected)


def test_determine_user_key_for_access_github_org():
    cluster_info = {"auth": {"service": "github-org"}}
    user_key = sut.determine_user_key_for_access(cluster_info)
    assert user_key == "github_username"


def test_determine_user_key_for_access_github_org_team():
    cluster_info = {"auth": {"service": "github-org-team"}}
    user_key = sut.determine_user_key_for_access(cluster_info)
    assert user_key == "github_username"


def test_determine_user_key_for_access_oidc():
    cluster_info = {"auth": {"service": "oidc"}}
    user_key = sut.determine_user_key_for_access(cluster_info)
    assert user_key == "org_username"


def test_determine_user_key_for_access_not_implemented():
    cluster_info = {"auth": {"service": "not-implemented"}, "name": "c"}
    with pytest.raises(NotImplementedError):
        sut.determine_user_key_for_access(cluster_info)
