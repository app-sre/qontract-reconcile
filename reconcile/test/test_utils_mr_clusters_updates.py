from unittest import TestCase
from unittest.mock import MagicMock

from ruamel import yaml

import reconcile.utils.mr.clusters_updates as sut

from .fixtures import Fixtures

fxt = Fixtures('clusters')


class TrivialClustersUpdates(sut.CreateClustersUpdates):
    # pylint: disable=super-init-not-called
    def __init__(self, clusters_updates):
        self.cancelled = False
        self.message = ''
        self.clusters_updates = clusters_updates
        self.branch = 'abranch'
        self.main_branch = 'main'

    def cancel(self, message):
        self.cancelled = True
        self.message = message


class TestProcess(TestCase):
    def setUp(self):
        self.clusters = [
            fxt.get_anymarkup('cluster1.yml')
        ]
        self.raw_clusters = fxt.get('cluster1.yml')

    def test_no_changes(self):
        cli = MagicMock()
        c = TrivialClustersUpdates({})
        c.process(cli)
        self.assertTrue(c.cancelled)

        cli.project.files.get.assert_not_called()

    def test_changes_to_spec(self):
        cli = MagicMock()
        cli.project.files.get.return_value = self.raw_clusters.encode()
        c = TrivialClustersUpdates(
            {'cluster1': {'spec': {'id': '42'}, 'root': {}, 'path': '/a/path'}}
        )
        c.process(cli)
        self.clusters[0]['spec']['id'] = '42'

        cnt = yaml.dump(self.clusters[0],
                        Dumper=yaml.RoundTripDumper,
                        explicit_start=True)
        cli.update_file.assert_called_once_with(
            branch_name='abranch',
            file_path='/a/path',
            commit_message='update cluster cluster1 spec fields',
            content=cnt
        )
        self.assertFalse(c.cancelled)

    def test_changes_to_root(self):
        cli = MagicMock()
        cli.project.files.get.return_value = self.raw_clusters.encode()
        c = TrivialClustersUpdates(
            {'cluster1': {
                'spec': {},
                'root': {'prometheusUrl': 'aprometheusurl'},
                'path': '/a/path'}
             }
        )
        c.process(cli)
        self.clusters[0]['prometheusUrl'] = 'aprometheusurl'

        cnt = yaml.dump(self.clusters[0],
                        Dumper=yaml.RoundTripDumper,
                        explicit_start=True)
        cli.update_file.assert_called_once_with(
            branch_name='abranch',
            file_path='/a/path',
            commit_message='update cluster cluster1 spec fields',
            content=cnt
        )
        self.assertFalse(c.cancelled)
