import json
from typing import Optional
from unittest import TestCase
from unittest.mock import (
    Mock,
    call,
    patch,
)

from reconcile import openshift_namespace_labels
from reconcile.openshift_namespace_labels import state_key


# TODO: use a dataclass when python > 3.6
class NS:
    """
    Simple utility class holding test information about current,
    desired and managed labels for a single cluster/namespace. It allows to
    simplify the test data creation.
    Some methods are there to convert this data into GQL, State or OC outputs.
    """

    def __init__(
        self,
        cluster: str,
        name: str,
        current: Optional[dict[str, str]],
        managed: Optional[list[str]],
        desired: dict[str, str],
        exists: bool = True,
    ):
        self.cluster = cluster
        self.name = name
        self.current = current
        self.managed = managed
        self.desired = desired
        self.exists = exists

    def gql(self):
        """Get this namespace as an output of GQL"""
        d = {"name": self.name, "cluster": {"name": self.cluster}}
        if self.desired is not None:
            d["labels"] = json.dumps(self.desired)
        return d

    def oc_get_all(self):
        """Get this namespace as an output of oc get namespace"""
        if not self.exists:
            return None
        d = {"metadata": {"name": self.name}}
        if self.current:
            d["metadata"]["labels"] = self.current
        return d

    def state_key(self):
        """Get the managed state key for this namespace"""
        return state_key(self.cluster, self.name)


# Some shortcuts
c1, c2 = "cluster1", "cluster2"
k1v1, k2v2, k3v3, k1v2 = {"k1": "v1"}, {"k2": "v2"}, {"k3": "v3"}, {"k1": "v2"}
k1v1_k2v2, k2v3_k3v3 = {"k1": "v1", "k2": "v2"}, {"k2": "v3", "k3": "v3"}
k1, k2, k1_k2, k2_k3 = ["k1"], ["k2"], ["k1", "k2"], ["k2", "k3"]
k1_k2_k3 = ["k1", "k2", "k3"]


def run_integration(
    dry_run=False,
    thread_pool_size=1,
    internal=None,
    use_jump_host=True,
    raise_errors=True,
):
    """Calls the integration with sensible overridable defaults"""
    openshift_namespace_labels.run(
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        raise_errors=raise_errors,
    )


class TestOpenshiftNamespaceLabels(TestCase):
    """
    This test case class runs the full openshift-namespace-labels integration
    in several cases. For this we mock OC, State and GQL queries, patching them
    with functions that use the individual tests data from self.test_ns.
    This allows to code teh mock logic only once.
    """

    def _queries_get_namespaces(self):
        """Mock queries.get_namespaces() by returning our test data"""
        return [ns.gql() for ns in self.test_ns]

    def _oc_map_clusters(self):
        """Mock OCM_Map.clusters() by listing clusters in our test data"""
        return list({ns.cluster for ns in self.test_ns if ns.exists})

    def _oc_map_get(self, cluster):
        """Mock OCM_Map.get() by getting namespaces from our test data"""
        oc = self.oc_clients.setdefault(cluster, Mock(name=f"oc_{cluster}"))
        ns = [
            ns.oc_get_all()
            for ns in self.test_ns
            if ns.exists and ns.cluster == cluster
        ]
        oc.get_all.return_value = {"items": ns}
        return oc

    def _state_ls(self):
        """Mock State.ls() by getting state keys from our test data"""
        return [f"/{ns.state_key()}" for ns in self.test_ns if ns.managed is not None]

    def _ns_from_key(self, key):
        """Get a namespace from test data, matching the provided state key"""
        for ns in self.test_ns:
            if key == ns.state_key():
                return ns
        return None

    def _state_get(self, key, default):
        """Mock State.get() by getting managed state from our test data"""
        ns = self._ns_from_key(key)
        if ns is not None:
            return ns.managed
        return default

    # We could avoid implementing this method.
    # We just ensure it is called with correct parameters
    def _state_add(self, key, value=None, force=False):
        """Mock State.add() by updating our test data"""
        ns = self._ns_from_key(key)
        self.assertIsNotNone(ns)
        ns.managed = value

    def setUp(self):
        """Setup GQL, State and Openshift mocks, using self.test_ns data"""
        self.test_ns = []
        self.oc_clients = {}

        module = "reconcile.openshift_namespace_labels"

        # mock all {module}.queries functions
        # with a side_effect on get_namespaces only
        self.queries_patcher = patch(f"{module}.queries")
        self.queries = self.queries_patcher.start()
        self.queries.get_namespaces.side_effect = self._queries_get_namespaces

        self.oc_map_patcher = patch(f"{module}.OC_Map")
        self.oc_map = self.oc_map_patcher.start().return_value
        self.oc_map.clusters.side_effect = self._oc_map_clusters
        self.oc_map.get.side_effect = self._oc_map_get

        self.state_patcher = patch(f"{module}.State")
        self.state = self.state_patcher.start().return_value
        self.state.ls.side_effect = self._state_ls
        self.state.get.side_effect = self._state_get
        self.state.add.side_effect = self._state_add

    def tearDown(self) -> None:
        """cleanup patches created in self.setUp"""
        self.oc_map_patcher.stop()
        self.queries_patcher.stop()
        self.state_patcher.stop()

    def test_no_change(self):
        """No label change: nothing should be done"""
        self.test_ns = [
            NS(c1, "no-change", k1v1, k1, k1v1),
        ]
        run_integration()
        self.state.add.assert_not_called()
        for oc in self.oc_clients.values():
            oc.label.assert_not_called()

    def test_update(self):
        """single label value change"""
        self.test_ns = [
            NS(c1, "update", k1v1, k1, k1v2),
        ]
        run_integration()
        # no change in the managed key store: we have the same keys than before
        self.state.add.assert_not_called()
        oc = self.oc_clients[c1]
        oc.label.assert_called_once_with(
            None, "Namespace", "update", k1v2, overwrite=True
        )

    def test_add(self):
        """addition of a label"""
        self.test_ns = [
            NS(c1, "add", k1v1, k1, k1v1_k2v2),
        ]
        run_integration()
        self.state.add.assert_called_once_with(state_key(c1, "add"), k1_k2, force=True)
        oc = self.oc_clients[c1]
        oc.label.assert_called_once_with(None, "Namespace", "add", k2v2, overwrite=True)

    def test_add_from_none(self):
        """addition of a label from none on the current namespace"""
        self.test_ns = [
            NS(c1, "add-from-none", {}, None, k1v1),
        ]
        run_integration()
        self.state.add.assert_called_once_with(
            state_key(c1, "add-from-none"), k1, force=True
        )
        oc = self.oc_clients[c1]
        oc.label.assert_called_once_with(
            None, "Namespace", "add-from-none", k1v1, overwrite=True
        )

    def test_remove_step1(self):
        """removal of a label step 1: remove label"""
        self.test_ns = [
            NS(c1, "remove", k1v1_k2v2, k1_k2, k1v1),
        ]
        run_integration()
        self.state.add.assert_not_called()
        oc = self.oc_clients[c1]
        oc.label.assert_called_once_with(
            None, "Namespace", "remove", {"k2": None}, overwrite=True
        )

    def test_remove_step2(self):
        """removal of a label step 2: remove key from managed state"""
        self.test_ns = [
            NS(c1, "remove", k1v1, k1_k2, k1v1),
        ]
        run_integration()
        self.state.add.assert_called_once_with(state_key(c1, "remove"), k1, force=True)
        oc = self.oc_clients[c1]
        oc.label.assert_not_called()

    def test_remove_add_modify_step1(self):
        """Remove, add and modify labels all at once, step 1 (removals are in
        two steps)"""
        self.test_ns = [
            NS(c1, "all-in-one", k1v1_k2v2, k1_k2, k2v3_k3v3),
        ]
        run_integration()
        self.state.add.assert_called_once_with(
            state_key(c1, "all-in-one"), k1_k2_k3, force=True
        )
        oc = self.oc_clients[c1]
        labels = {"k1": None, "k2": "v3", "k3": "v3"}
        oc.label.assert_called_once_with(
            None, "Namespace", "all-in-one", labels, overwrite=True
        )

    def test_remove_add_modify_step2(self):
        """Remove, add and modify labels all at once, step 2 (removals are in
        two steps)"""
        self.test_ns = [
            NS(c1, "all-in-one", k2v3_k3v3, k1_k2_k3, k2v3_k3v3),
        ]
        run_integration()
        self.state.add.assert_called_once_with(
            state_key(c1, "all-in-one"), k2_k3, force=True
        )
        oc = self.oc_clients[c1]
        oc.label.assert_not_called()

    def test_namespace_not_exists(self):
        """namespace does not exist (yet)"""
        self.test_ns = [
            NS(c1, "not-exists", None, None, k1v1, exists=False),
        ]
        run_integration()
        self.state.add.assert_not_called()
        self.assertNotIn(c1, self.oc_clients.keys())

    def test_duplicate_namespace(self):
        """Namespace declared several times in a single cluster: ignored"""
        self.test_ns = [
            NS(c1, "no-change", k1v1, k1, k1v1),
            NS(c1, "no-change", k1v1, k1, k2v2),
            NS(c1, "no-change", k1v1, k1, k1v2),
        ]
        run_integration()
        self.state.add.assert_not_called()
        for oc in self.oc_clients.values():
            oc.label.assert_not_called()

    def test_multi_cluster(self):
        """Namespace declared in several clusters. All get updated"""
        self.test_ns = [
            NS(c1, "multi-cluster", k1v1, k1, k1v1_k2v2),
            NS(c2, "multi-cluster", k1v1, k1, k1v1_k2v2),
        ]
        run_integration()
        self.assertEqual(self.state.add.call_count, 2)
        calls = [
            call(state_key(c1, "multi-cluster"), k1_k2, force=True),
            call(state_key(c2, "multi-cluster"), k1_k2, force=True),
        ]
        self.state.add.assert_has_calls(calls)

        self.assertIn(c1, self.oc_clients)
        self.assertIn(c2, self.oc_clients)
        for oc in self.oc_clients.values():
            oc.label.assert_called_once_with(
                None, "Namespace", "multi-cluster", k2v2, overwrite=True
            )

    def test_dry_run(self):
        """Ensures nothing is done in dry_run mode"""
        self.test_ns = [
            NS(c1, "many-changes", k1v1_k2v2, k1_k2, k2v3_k3v3),
        ]
        run_integration(dry_run=True)
        self.state.add.assert_not_called()
        oc = self.oc_clients[c1]
        oc.label.assert_not_called()
