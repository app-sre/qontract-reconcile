from typing import List, cast

import testslide
import reconcile.openshift_base as sut
import reconcile.utils.openshift_resource as resource
import reconcile.utils.oc as oc


class TestInitSpecsToFetch(testslide.TestCase):

    def setUp(self) -> None:
        super().setUp()
        self.resource_inventory = cast(
            resource.ResourceInventory,
            testslide.StrictMock(resource.ResourceInventory)
        )

        self.oc_map = cast(oc.OC_Map, testslide.StrictMock(oc.OC_Map))
        self.mock_constructor(oc, 'OC_Map').to_return_value(self.oc_map)
        self.namespaces = [
            {
                "name": "ns1",
                "managedResourceTypes": ["Template"],
                "cluster": {"name": "cs1"},
                "managedResourceNames": [
                    {"resource": "Template",
                     "resourceNames": ["tp1", "tp2"],
                     },
                    {"resource": "Secret",
                     "resourceNames": ["sc1"],
                     }
                ],
                "openshiftResources": [
                    {"provider": "resource",
                     "path": "/some/path.yml"
                     }
                ]
            }
        ]

        self.mock_callable(
            self.resource_inventory, 'initialize_resource_type'
        ).for_call(
            'cs1', 'ns1', 'Template'
        ).to_return_value(None)

        self.mock_callable(
            self.oc_map, 'get'
        ).for_call("cs1").to_return_value("stuff")
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)

    def test_only_cluster_or_namespace(self) -> None:
        with self.assertRaises(KeyError):
            sut.init_specs_to_fetch(
                self.resource_inventory,
                self.oc_map,
                [{"foo": "bar"}],
                [{"name": 'cluster1'}],
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
                resource={
                    "provider": "resource",
                    "path": "/some/path.yml"
                },
                parent=self.namespaces[0]
            )
        ]

        rs = sut.init_specs_to_fetch(
                self.resource_inventory,
                self.oc_map,
                namespaces=self.namespaces,
            )

        self.maxDiff = None
        self.assert_specs_match(rs, expected)

    def test_namespaces_managed_with_overrides(self) -> None:
        self.namespaces[0]['managedResourceTypeOverrides'] = [
            {
                "resource": "Project",
                "override": "something.project",
            },
            {
                "resource": "Template",
                "override": "something.template"
            }
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
                resource={
                    "provider": "resource",
                    "path": "/some/path.yml"
                },
                parent=self.namespaces[0]
            )
        ]
        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            self.oc_map,
            namespaces=self.namespaces,
        )

        self.assert_specs_match(rs, expected)

    def test_namespaces_no_managedresourcenames(self) -> None:
        self.namespaces[0]['managedResourceNames'] = None
        self.namespaces[0]['managedResourceTypeOverrides'] = None

        expected = [
            sut.StateSpec(
                type="desired",
                oc="stuff",
                cluster="cs1",
                namespace="ns1",
                resource={
                    "provider": "resource",
                    "path": "/some/path.yml"
                },
                parent=self.namespaces[0]
            )
        ]
        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            self.oc_map,
            namespaces=self.namespaces,
        )
        self.assert_specs_match(rs, expected)

    def test_namespaces_no_managedresourcetypes(self) -> None:
        self.namespaces[0]['managedResourceTypes'] = None

        rs = sut.init_specs_to_fetch(
            self.resource_inventory,
            self.oc_map,
            namespaces=self.namespaces,
        )
        self.assertEqual(rs, [])
