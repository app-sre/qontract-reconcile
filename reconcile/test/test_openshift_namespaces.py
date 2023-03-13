import contextlib
import io
from unittest import TestCase
from unittest.mock import (
    Mock,
    create_autospec,
    patch,
)

from reconcile import openshift_namespaces
from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.common.namespaces_minimal import NamespaceV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.secret_reader import SecretReaderBase

fxt = Fixtures("openshift_namespaces")


def load_namespace(name: str) -> NamespaceV1:
    content = fxt.get_anymarkup(name)
    return NamespaceV1(**content)


c1, c2 = "cluster1", "cluster2"
n1, n2 = "ns1", "ns2"


class NS:
    """
    Simple utility class holding test information on namesapces
    """

    def __init__(self, cluster: str, name: str, delete: bool, exists: bool = True):
        self.cluster = cluster
        self.name = name
        self.delete = delete
        self.exists = exists

    def gql(self):
        """Get this namespace as an output of GQL"""
        ns = load_namespace("namespace.yml")
        ns.name = self.name
        ns.cluster.name = self.cluster
        ns.delete = self.delete
        return ns


class TestOpenshiftNamespaces(TestCase):
    def _oc_map_clusters(self):
        """Mock OCM_Map.clusters() by listing clusters in our test data"""
        return [ns.name for ns in self.test_ns]

    def _project_exists(self, project) -> bool:
        for ns in self.test_ns:
            if ns.name == project and ns.cluster == self.current_cluster:
                return ns.exists
        return False

    def _oc_map_get(self, cluster):
        """Mock OCM_Map.get() to return a Mock object"""
        self.current_cluster = cluster
        if cluster not in self.oc_clients:
            # The mock could be set in the test to override this behavior
            oc = self.oc_clients.setdefault(cluster, Mock(name=f"oc_{cluster}"))
            oc.project_exists.side_effect = self._project_exists
        else:
            oc = self.oc_clients[cluster]
        return oc

    def _queries_get_namespaces(self):
        """Mock get_namespaces() by returning our test data
        gql_response is set in the test method.
        """
        return [ns.gql() for ns in self.test_ns]

    def setUp(self):
        """Setup GQL, State and Openshift mocks, using self.test_ns data"""
        self.oc_clients = {}
        self.test_ns = []

        module = "reconcile.openshift_namespaces"

        self.queries_patcher = patch(f"{module}.get_namespaces_minimal", autospec=True)
        self.queries = self.queries_patcher.start()
        self.queries.side_effect = self._queries_get_namespaces

        vault_settings = AppInterfaceSettingsV1(vault=False)
        self.get_vault_settings_patcher = patch(
            f"{module}.get_app_interface_vault_settings"
        )
        self.get_vault_settings = self.get_vault_settings_patcher.start()
        self.get_vault_settings.side_effect = [vault_settings]

        self.create_secret_reader_patcher = patch(f"{module}.create_secret_reader")
        self.create_secret_reader = self.create_secret_reader_patcher.start()
        self.create_secret_reader.side_effect = [create_autospec(spec=SecretReaderBase)]

        self.oc_map_patcher = patch(f"{module}.init_oc_map_from_namespaces")
        self.oc_map = self.oc_map_patcher.start().return_value
        self.oc_map.clusters.side_effect = self._oc_map_clusters
        self.oc_map.get.side_effect = self._oc_map_get

    def tearDown(self) -> None:
        self.oc_map_patcher.stop()
        self.queries_patcher.stop()

    def test_create_namespace(self):
        self.test_ns = [
            NS(c1, n1, delete=False, exists=False),
            NS(c2, n2, delete=False, exists=False),
        ]

        openshift_namespaces.run(False, thread_pool_size=1)

        for ns in self.test_ns:
            oc = self.oc_clients[ns.cluster]
            oc.new_project.assert_called_with(ns.name)
            oc.delete_project.assert_not_called()

    def test_delete_namespace(self):
        self.test_ns = [
            NS(c1, n1, delete=True, exists=True),
            NS(c2, n2, delete=True, exists=True),
        ]

        openshift_namespaces.run(False, thread_pool_size=1)

        for ns in self.test_ns:
            oc = self.oc_clients[ns.cluster]
            oc.delete_project.assert_called_with(ns.name)
            oc.new_project.assert_not_called()

    def test_dup_present_namespace_no_deletes_should_do_nothing(self):
        self.test_ns = [
            NS(c1, n1, delete=False, exists=True),
            NS(c1, n1, delete=False, exists=True),
            NS(c1, n1, delete=False, exists=True),
        ]
        openshift_namespaces.run(False, thread_pool_size=1)
        oc = self.oc_clients[c1]
        oc.delete_project.assert_not_called()
        oc.new_project.assert_not_called()

    def test_dup_present_namespace_some_deletes_should_error(self):
        self.test_ns = [
            NS(c1, n1, delete=False, exists=True),
            NS(c1, n1, delete=True, exists=True),
            NS(c1, n1, delete=True, exists=True),
            NS(c1, n2, delete=False, exists=True),
        ]
        f = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(f):
            openshift_namespaces.run(False, thread_pool_size=1)
            self.assertIn("Found multiple definitions", f.getvalue())

        oc = self.oc_clients[c1]
        oc.delete_project.assert_not_called()
        oc.new_project.assert_not_called()

    def test_dup_present_namespace_all_deletes_should_delete(self):
        self.test_ns = [
            NS(c1, n1, delete=True, exists=True),
            NS(c1, n1, delete=True, exists=True),
            NS(c1, n1, delete=True, exists=True),
        ]
        openshift_namespaces.run(False, thread_pool_size=1)
        oc = self.oc_clients[c1]
        oc.delete_project.assert_called()
        oc.new_project.assert_not_called()

    def test_dup_absent_namespace_no_deletes_should_create(self):
        self.test_ns = [
            NS(c1, n1, delete=False, exists=False),
            NS(c1, n1, delete=False, exists=False),
            NS(c1, n1, delete=False, exists=False),
        ]
        openshift_namespaces.run(False, thread_pool_size=1)
        oc = self.oc_clients[c1]
        oc.delete_project.assert_not_called()
        oc.new_project.assert_called()

    def test_dup_absent_namespace_some_deletes_should_error(self):
        self.test_ns = [
            NS(c1, n1, delete=True, exists=False),
            NS(c1, n1, delete=False, exists=False),
            NS(c1, n1, delete=False, exists=False),
            NS(c1, n2, delete=False, exists=True),
        ]

        f = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(f):
            openshift_namespaces.run(False, thread_pool_size=1)
            self.assertIn("Found multiple definitions", f.getvalue())

        oc = self.oc_clients[c1]
        oc.delete_project.assert_not_called()
        oc.new_project.assert_not_called()

    def test_dup_absent_namespace_all_deletes_should_do_nothing(self):
        self.test_ns = [
            NS(c1, n1, delete=True, exists=False),
            NS(c1, n1, delete=True, exists=False),
            NS(c1, n1, delete=True, exists=False),
        ]
        openshift_namespaces.run(False, thread_pool_size=1)
        oc = self.oc_clients[c1]
        oc.delete_project.assert_not_called()
        oc.new_project.assert_not_called()

    def test_delete_absent_namespace(self):
        self.test_ns = [
            NS(c1, n1, delete=True, exists=False),
        ]
        openshift_namespaces.run(False, thread_pool_size=1)

        oc = self.oc_clients[c1]
        oc.delete_project.assert_not_called()
        oc.new_project.assert_not_called()

    def test_error_handling_project_exists(self):
        oc = self.oc_clients.setdefault(c1, Mock(name=f"oc_{c1}"))
        oc.project_exists.side_effect = StatusCodeError("SomeError")
        self.oc_map.get.return_value = oc

        self.test_ns = [
            NS(c1, "project_raises_exception", delete=True, exists=False),
        ]
        f = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(f):
            openshift_namespaces.run(False, thread_pool_size=1)
            self.assertIn("SomeError", f.getvalue())

    def test_run_with_cluster_name(self):
        self.test_ns = [
            NS(c1, n1, delete=False, exists=False),
            NS(c2, n2, delete=False, exists=False),
        ]

        openshift_namespaces.run(False, thread_pool_size=1, cluster_name=c1)

        self.oc_clients[c1].new_project.assert_called_with(n1)
        self.assertNotIn(c2, self.oc_clients)

    def test_run_with_namespace_name(self):
        self.test_ns = [
            NS(c1, n1, delete=False, exists=False),
            NS(c2, n2, delete=False, exists=False),
        ]

        openshift_namespaces.run(False, thread_pool_size=1, namespace_name=n1)

        self.oc_clients[c1].new_project.assert_called_with(n1)
        self.assertNotIn(c2, self.oc_clients)
