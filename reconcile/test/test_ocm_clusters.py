import sys

from copy import deepcopy
from testslide import TestCase, StrictMock, mock_callable

from reconcile import queries

import reconcile.utils.ocm as ocmmod
import reconcile.ocm_clusters as occ
from reconcile.utils.mr import clusters_updates

from .fixtures import Fixtures

fxt = Fixtures("clusters")


class TestFetchDesiredState(TestCase):
    def setUp(self):
        self.clusters = [fxt.get_anymarkup("cluster1.yml")]

        self.maxDiff = None

    def test_all_fine(self):
        rs = occ.fetch_desired_state(self.clusters)

        self.assertEqual(
            rs,
            {
                "cluster1": {
                    "spec": self.clusters[0]["spec"],
                    "network": self.clusters[0]["network"],
                    "consoleUrl": "",
                    "serverUrl": "",
                    "elbFQDN": "",
                }
            },
        )


class TestGetClusterUpdateSpec(TestCase):
    def setUp(self):
        self.clusters = [fxt.get_anymarkup("cluster1.yml")]

    def test_no_changes(self):
        self.assertEqual(
            occ.get_cluster_update_spec("cluster1", self.clusters[0], self.clusters[0]),
            ({}, False),
        )

    def test_valid_change(self):
        desired = deepcopy(self.clusters[0])
        desired["spec"]["instance_type"] = "m42.superlarge"
        self.assertEqual(
            occ.get_cluster_update_spec(
                "cluster1",
                self.clusters[0],
                desired,
            ),
            ({"instance_type": "m42.superlarge"}, False),
        )

    def test_changed_network_banned(self):
        desired = deepcopy(self.clusters[0])
        self.clusters[0]["network"]["vpc"] = "10.0.0.0/8"
        self.assertEqual(
            occ.get_cluster_update_spec("cluster1", self.clusters[0], desired),
            ({}, True),
        )

    def test_changed_spec_bad(self):
        desired = deepcopy(self.clusters[0])
        desired["spec"]["multi_az"] = not desired["spec"]["multi_az"]
        self.assertTrue(
            occ.get_cluster_update_spec("cluster1", self.clusters[0], desired)[1],
        )

    def test_changed_disable_uwm(self):
        desired = deepcopy(self.clusters[0])

        desired["spec"][ocmmod.DISABLE_UWM_ATTR] = True
        self.assertEqual(
            occ.get_cluster_update_spec("cluster1", self.clusters[0], desired),
            ({ocmmod.DISABLE_UWM_ATTR: True}, False),
        )

    def test_non_set_disable_uwm(self):
        desired = deepcopy(self.clusters[0])
        self.clusters[0]["spec"][ocmmod.DISABLE_UWM_ATTR] = True
        self.assertEqual(
            occ.get_cluster_update_spec("cluster1", self.clusters[0], desired),
            ({}, False),
        )


class TestRun(TestCase):
    def setUp(self):
        super().setUp()
        self.clusters = [fxt.get_anymarkup("cluster1.yml")]
        self.clusters[0]["ocm"]["name"] = "ocm-nonexisting"
        self.clusters[0]["path"] = "/openshift/mycluster/cluster.yml"
        self.mock_callable(
            queries, "get_app_interface_settings"
        ).for_call().to_return_value({}).and_assert_called_once()
        self.get_clusters = (
            self.mock_callable(queries, "get_clusters")
            .for_call()
            .to_return_value(self.clusters)
            .and_assert_called_once()
        )
        self.ocmmap = StrictMock(ocmmod.OCMMap)
        self.ocm = StrictMock(ocmmod.OCM)
        self.mock_constructor(ocmmod, "OCMMap").to_return_value(self.ocmmap)
        self.mock_callable(self.ocmmap, "get").for_call("cluster1").to_return_value(
            self.ocm
        )
        self.update_cluster = self.mock_callable(
            self.ocm, "update_cluster"
        ).to_return_value(None)
        self.mock_callable(sys, "exit").to_raise(ValueError)
        self.addCleanup(mock_callable.unpatch_all_callable_mocks)

    def test_no_op_dry_run(self):
        self.clusters[0]["spec"]["id"] = "aclusterid"
        self.clusters[0]["spec"]["id"] = "anid"
        self.clusters[0]["spec"]["external_id"] = "anotherid"
        current = {
            "cluster1": {
                "spec": self.clusters[0]["spec"],
                "network": self.clusters[0]["network"],
                "consoleUrl": "aconsoleurl",
                "serverUrl": "aserverurl",
                "elbFQDN": "anelbfqdn",
            }
        }
        desired = deepcopy(current)
        current["cluster1"]["spec"].pop("initial_version")
        self.mock_callable(occ, "fetch_desired_state").to_return_value(
            desired
        ).and_assert_called_once()
        self.mock_callable(self.ocmmap, "cluster_specs").for_call().to_return_value(
            (current, {})
        ).and_assert_called_once()
        self.mock_callable(occ, "get_cluster_update_spec").to_return_value(
            ({}, False)
        ).and_assert_called_once()
        with self.assertRaises(ValueError) as e:
            occ.run(True)
            self.assertEqual(e.args, (0,))

    def test_no_op(self):
        self.clusters[0]["spec"]["id"] = "anid"
        self.clusters[0]["spec"]["external_id"] = "anotherid"
        current = {
            "cluster1": {
                "spec": self.clusters[0]["spec"],
                "network": self.clusters[0]["network"],
                "consoleUrl": "aconsoleurl",
                "serverUrl": "aserverurl",
                "elbFQDN": "anelbfqdn",
                "prometheusUrl": "aprometheusurl",
                "alertmanagerUrl": "analertmanagerurl",
            }
        }
        desired = deepcopy(current)
        current["cluster1"]["spec"].pop("initial_version")

        self.mock_callable(occ, "fetch_desired_state").to_return_value(
            desired
        ).and_assert_called_once()
        self.mock_callable(occ.mr_client_gateway, "init").for_call(
            gitlab_project_id=None
        ).to_return_value("not a value").and_assert_called_once()
        self.mock_callable(self.ocmmap, "cluster_specs").for_call().to_return_value(
            (current, {})
        ).and_assert_called_once()
        self.mock_callable(occ, "get_cluster_update_spec").to_return_value(
            ({}, False)
        ).and_assert_called_once()
        with self.assertRaises(ValueError) as e:
            occ.run(False)
            self.assertEqual(e.args, (0,))

    def test_changed_id(self):
        current = {
            "cluster1": {
                "spec": self.clusters[0]["spec"],
                "network": self.clusters[0]["network"],
                "consoleUrl": "aconsoleurl",
                "serverUrl": "aserverurl",
                "elbFQDN": "anelbfqdn",
                "prometheusUrl": "aprometheusurl",
                "alertmanagerUrl": "analertmanagerurl",
            }
        }
        desired = deepcopy(current)
        self.clusters[0]["spec"]["id"] = "anid"
        self.clusters[0]["spec"]["external_id"] = "anotherid"
        self.mock_callable(occ, "fetch_desired_state").to_return_value(
            desired
        ).and_assert_called_once()
        self.mock_callable(occ.mr_client_gateway, "init").for_call(
            gitlab_project_id=None
        ).to_return_value("not a value").and_assert_called_once()
        self.mock_callable(self.ocmmap, "cluster_specs").for_call().to_return_value(
            (current, {})
        ).and_assert_called_once()
        self.mock_callable(occ, "get_cluster_update_spec").to_return_value(
            ({"id": "anid"}, False)
        ).and_assert_called_once()
        create_clusters_updates = StrictMock(clusters_updates.CreateClustersUpdates)
        self.mock_constructor(
            clusters_updates, "CreateClustersUpdates"
        ).to_return_value(create_clusters_updates)
        self.mock_callable(create_clusters_updates, "submit").for_call(
            cli="not a value"
        ).to_return_value(None).and_assert_called_once()
        with self.assertRaises(ValueError) as e:
            occ.run(False)
            self.assertEqual(e.args, (0,))

    def test_changed_disable_uwm(self):
        current = {
            "cluster1": {
                "spec": self.clusters[0]["spec"],
                "network": self.clusters[0]["network"],
                "consoleUrl": "aconsoleurl",
                "serverUrl": "aserverurl",
                "elbFQDN": "anelbfqdn",
                "prometheusUrl": "aprometheusurl",
                "alertmanagerUrl": "analertmanagerurl",
            }
        }
        self.clusters[0]["spec"]["id"] = "id"
        self.clusters[0]["spec"]["external_id"] = "ext_id"

        desired = deepcopy(current)
        desired["cluster1"]["spec"][ocmmod.DISABLE_UWM_ATTR] = True

        self.mock_callable(occ, "fetch_desired_state").to_return_value(
            desired
        ).and_assert_called_once()

        self.mock_callable(occ.mr_client_gateway, "init").for_call(
            gitlab_project_id=None
        ).to_return_value("not a value").and_assert_called_once()

        self.mock_callable(self.ocmmap, "cluster_specs").for_call().to_return_value(
            (current, {})
        ).and_assert_called_once()

        create_clusters_updates = StrictMock(clusters_updates.CreateClustersUpdates)
        self.mock_constructor(
            clusters_updates, "CreateClustersUpdates"
        ).to_return_value(create_clusters_updates)

        self.mock_callable(create_clusters_updates, "submit").for_call(
            cli="not a value"
        ).to_return_value(None).and_assert_not_called()

        with self.assertRaises(ValueError) as e:
            occ.run(False)
            self.assertEqual(e.args, (0,))

    def test_non_set_disable_uwm(self):
        current = {
            "cluster1": {
                "spec": self.clusters[0]["spec"],
                "network": self.clusters[0]["network"],
                "consoleUrl": "aconsoleurl",
                "serverUrl": "aserverurl",
                "elbFQDN": "anelbfqdn",
                "prometheusUrl": "aprometheusurl",
                "alertmanagerUrl": "analertmanagerurl",
            }
        }
        self.clusters[0]["spec"]["id"] = "id"
        self.clusters[0]["spec"]["external_id"] = "ext_id"

        desired = deepcopy(current)
        self.clusters[0]["spec"][ocmmod.DISABLE_UWM_ATTR] = True

        self.mock_callable(occ, "fetch_desired_state").to_return_value(
            desired
        ).and_assert_called_once()

        self.mock_callable(occ.mr_client_gateway, "init").for_call(
            gitlab_project_id=None
        ).to_return_value("not a value").and_assert_called_once()

        self.mock_callable(self.ocmmap, "cluster_specs").for_call().to_return_value(
            (current, {})
        ).and_assert_called_once()

        create_clusters_updates = StrictMock(clusters_updates.CreateClustersUpdates)
        self.mock_constructor(
            clusters_updates, "CreateClustersUpdates"
        ).to_return_value(create_clusters_updates)

        self.mock_callable(create_clusters_updates, "submit").for_call(
            cli="not a value"
        ).to_return_value(None).and_assert_called_once()

        with self.assertRaises(ValueError) as e:
            occ.run(False)
            self.assertEqual(e.args, (0,))
