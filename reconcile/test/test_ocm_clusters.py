from collections import ChainMap
from unittest import TestCase
from unittest.mock import patch
from .fixtures import Fixtures

import reconcile.ocm_clusters as occ

fxt = Fixtures('clusters')


class TestFetchDesiredState(TestCase):
    def setUp(self):
        self.clusters = [
            fxt.get_anymarkup('cluster1.yml')
        ]

        self.maxDiff = None

    def test_all_fine(self):
        rs = occ.fetch_desired_state(self.clusters)

        self.assertEquals(
            rs,
            {
                'cluster1': {
                    'spec': self.clusters[0]['spec'],
                    'network': self.clusters[0]['network'],
                    'consoleUrl': '',
                    'serverUrl': '',
                    'elbFQDN': '',
                    'prometheusUrl': '',
                    'alertmanagerUrl': ''
                }
            }
        )


class TestGetClusterUpdateSpec(TestCase):
    def setUp(self):
        self.clusters = [
            fxt.get_anymarkup('cluster1.yml')
        ]

    def test_no_changes(self):
        self.assertEqual(
            occ.get_cluster_update_spec(
                'cluster1',
                self.clusters[0],
                self.clusters[0]
            ),
            ({}, False)
        )

    def test_valid_change(self):
        desired = copy.deepcopy(self.clusters[0])
        desired['spec']['instance_type'] = 'm42.superlarge'
        print(desired)
        print(self.clusters[0])
        self.assertEqual(
            occ.get_cluster_update_spec(
                'cluster1',
                self.clusters[0],
                desired,
            ),
            ({'instance_type': 'm42.superlarge'}, False)
        )

    def test_changed_network(self):
        desired = copy.deepcopy(self.clusters[0])
        self.clusters[0]['network']['vpc'] = '10.0.0.0/8'
        self.assertEqual(
            occ.get_cluster_update_spec(
                'cluster1', self.clusters[0], desired
            ),
            ({}, True)
        )


class TestRun(TestCase):
    pass
