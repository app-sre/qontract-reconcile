import contextlib
import io
from unittest import TestCase
from unittest.mock import Mock, patch
from reconcile import openshift_namespaces
from reconcile.utils.oc import StatusCodeError


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
        d = {
            "name": self.name,
            "cluster": {"name": self.cluster},
            "delete": self.delete,
        }
        return d


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

    def _queries_get_namespaces(self, minimal=False):
        """Mock queries.get_namespaces() by returning our test data
        gql_response is set in the test method.
        """
        return [ns.gql() for ns in self.test_ns]

    def setUp(self):
        """Setup GQL, State and Openshift mocks, using self.test_ns data"""
        self.oc_clients = {}
        self.test_ns = []

        module = "reconcile.openshift_namespaces"

        self.queries_patcher = patch(f"{module}.queries", autospec=True)
        self.queries = self.queries_patcher.start()
        self.queries.get_namespaces.side_effect = self._queries_get_namespaces

        self.oc_map_patcher = patch(f"{module}.OC_Map", autospec=True)
        self.oc_map = self.oc_map_patcher.start().return_value
        self.oc_map.clusters.side_effect = self._oc_map_clusters
        self.oc_map.get.side_effect = self._oc_map_get

    def tearDown(self) -> None:
        self.oc_map_patcher.stop()
        self.queries_patcher.stop()

    def test_create_namespace(self):
        self.test_ns = [
            NS(c1, n1, delete=False, exists=False),
        ]

        openshift_namespaces.run(False, thread_pool_size=1)
        oc = self.oc_clients[c1]
        oc.new_project.assert_called_with(n1)
        oc.delete_project.assert_not_called()

    def test_delete_namespace(self):
        self.test_ns = [
            NS(c1, n1, delete=True, exists=True),
        ]

        openshift_namespaces.run(False, thread_pool_size=1)
        oc = self.oc_clients[c1]
        oc.delete_project.assert_called_with(n1)
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
