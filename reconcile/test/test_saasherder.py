import yaml

from unittest import TestCase
from unittest.mock import patch, MagicMock

from .fixtures import Fixtures

from github import GithubException

from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.saasherder import SaasHerder


class TestCheckSaasFileEnvComboUnique(TestCase):
    def test_check_saas_file_env_combo_unique(self):
        saas_files = [
            {
                'path': 'path1',
                'name': 'a1',
                'managedResourceTypes': [],
                'resourceTemplates':
                [
                    {
                        'name': 'rt',
                        'targets':
                        [
                            {
                                'namespace': {
                                    'name': 'ns',
                                    'environment': {
                                        'name': 'env1'
                                    },
                                    'cluster': {
                                        'name': 'cluster'
                                    }
                                },
                                'parameters': {}
                            },
                            {
                                'namespace': {
                                    'name': 'ns',
                                    'environment': {
                                        'name': 'env2'
                                    },
                                    'cluster': {
                                        'name': 'cluster'
                                    }
                                },
                                'parameters': {}
                            }
                        ]
                    }
                ],
                'roles': [
                    {'users': [{'org_username': 'myname'}]}
                ]
            }
        ]
        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={},
            validate=True
        )

        self.assertTrue(saasherder.valid)

    def test_check_saas_file_env_combo_not_unique(self):
        saas_files = [
            {
                'path': 'path1',
                'name':
                'long-name-which-is-too-long-to-produce-unique-combo',
                'managedResourceTypes': [],
                'resourceTemplates':
                [
                    {
                        'name': 'rt',
                        'targets':
                        [
                            {
                                'namespace': {
                                    'name': 'ns',
                                    'environment': {
                                        'name': 'env1'
                                    },
                                    'cluster': {
                                        'name': 'cluster'
                                    }
                                },
                                'parameters': {}
                            },
                            {
                                'namespace': {
                                    'name': 'ns',
                                    'environment': {
                                        'name': 'env2'
                                    },
                                    'cluster': {
                                        'name': 'cluster'
                                    }
                                },
                                'parameters': {}
                            }
                        ]
                    }
                ],
                'roles': [
                    {'users': [{'org_username': 'myname'}]}
                ]
            }
        ]
        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={},
            validate=True
        )

        self.assertFalse(saasherder.valid)


class TestGetMovingCommitsDiffSaasFile(TestCase):
    def setUp(self):
        self.saas_files = [
            {
                'path': 'path1',
                'name': 'a1',
                'managedResourceTypes': [],
                'resourceTemplates':
                [
                    {
                        'name': 'rt',
                        'url': 'http://github.com/user/repo',
                        'targets':
                        [
                            {
                                'namespace': {
                                    'name': 'ns',
                                    'environment': {
                                        'name': 'env1'
                                    },
                                    'cluster': {
                                        'name': 'cluster1'
                                    }
                                },
                                'parameters': {},
                                'ref': 'main',
                            },
                            {
                                'namespace': {
                                    'name': 'ns',
                                    'environment': {
                                        'name': 'env2'
                                    },
                                    'cluster': {
                                        'name': 'cluster2'
                                    }
                                },
                                'parameters': {},
                                'ref': 'secondary'
                            }
                        ]
                    }
                ],
                'roles': [
                    {'users': [{'org_username': 'myname'}]}
                ]
            }
        ]
        self.initiate_gh_patcher = patch.object(
            SaasHerder, '_initiate_github', autospec=True
        )
        self.get_pipelines_provider_patcher = patch.object(
            SaasHerder, '_get_pipelines_provider'
        )
        self.get_commit_sha_patcher = patch.object(
            SaasHerder, '_get_commit_sha', autospec=True
        )
        self.initiate_gh = self.initiate_gh_patcher.start()
        self.get_pipelines_provider = \
            self.get_pipelines_provider_patcher.start()
        self.get_commit_sha = self.get_commit_sha_patcher.start()
        self.maxDiff = None

    def tearDown(self):
        for p in (
                self.initiate_gh_patcher,
                self.get_pipelines_provider_patcher,
                self.get_commit_sha_patcher
        ):
            p.stop()

    def test_get_moving_commits_diff_saas_file_all_fine(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={},
            validate=False
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = 'asha'
        self.get_commit_sha.side_effect = ('abcd4242', '4242efg')
        self.get_pipelines_provider.return_value = 'apipelineprovider'
        expected = [
            {
                'saas_file_name': self.saas_files[0]['name'],
                'env_name': 'env1',
                'timeout': None,
                'ref': 'main',
                'commit_sha': 'abcd4242',
                'cluster_name': 'cluster1',
                'pipelines_provider': 'apipelineprovider',
                'namespace_name': 'ns',
                'rt_name': 'rt',
            },
            {
                'saas_file_name': self.saas_files[0]['name'],
                'env_name': 'env2',
                'timeout': None,
                'ref': 'secondary',
                'commit_sha': '4242efg',
                'cluster_name': 'cluster2',
                'pipelines_provider': 'apipelineprovider',
                'namespace_name': 'ns',
                'rt_name': 'rt',
            }
        ]

        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(
                self.saas_files[0], True
            ),
            expected
        )

    def test_get_moving_commits_diff_saas_file_bad_sha1(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={},
            validate=False
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = 'asha'
        self.get_pipelines_provider.return_value = 'apipelineprovider'
        self.get_commit_sha.side_effect = GithubException(
            401, 'somedata', {'aheader': 'avalue'}
        )
        # At least we don't crash!
        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(
                self.saas_files[0], True
            ),
            []
        )


class TestPopulateDesiredState(TestCase):
    def setUp(self):
        saas_files = []
        fxt = Fixtures('saasfiles')
        for file in [fxt.get("saas_remote_openshift_template.yaml")]:
            saas_files.append(yaml.safe_load(file))

        self.assertEqual(1, len(saas_files))
        self.saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={'hashLength':  7}
        )
        self.fxt_remote_files = Fixtures('saasfiles_remote_repo')

        # Mock GitHub interactions.
        self.initiate_gh_patcher = patch.object(
            SaasHerder, '_initiate_github', autospec=True, return_value=None,
        )
        self.initiate_gh_patcher.start()

        self.get_file_contents_patcher = patch.object(
            SaasHerder, '_get_file_contents', wraps=self.fake_get_file_contents,
        )
        self.get_file_contents_patcher.start()

    # options keys: 'url, 'path', 'ref'
    def fake_get_file_contents(self, options):
        self.assertEqual('https://github.com/rhobs/configuration', options['url'])

        content = self.fxt_remote_files.get(options['ref'] + (options['path'].replace('/', '_')))
        return yaml.safe_load(content), "yolo", options['ref']

    def tearDown(self):
        for p in (
            self.initiate_gh_patcher,
            self.get_file_contents_patcher
        ):
            p.stop()

    def test_populate_desired_state_saas_file_delete(self):
        spec = {'delete': True}

        desired_state = self.saasherder.populate_desired_state_saas_file(spec, None)
        self.assertIsNone(desired_state)

    def test_populate_desired_state_cases(self):
        ir = ResourceInventory()
        self.saasherder.populate_desired_state(ir)

        # TODO(bwplotka): Assert correct resources.
        self.assertEqual({"yolo": "yolo"}, ir._clusters)


class TestGetSaasFileAttribute(TestCase):
    def test_attribute_none(self):
        saas_files = [
            {
                'path': 'path1',
                'name': 'name1',
                'managedResourceTypes': [],
                'resourceTemplates': []
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={}
        )
        att = saasherder._get_saas_file_feature_enabled('no_such_attribute')
        self.assertEqual(att, None)

    def test_attribute_not_none(self):
        saas_files = [
            {
                'path': 'path1',
                'name': 'name1',
                'managedResourceTypes': [],
                'resourceTemplates': [],
                'attrib': True
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={}
        )
        att = saasherder._get_saas_file_feature_enabled('attrib')
        self.assertEqual(att, True)

    def test_attribute_none_with_default(self):
        saas_files = [
            {
                'path': 'path1',
                'name': 'name1',
                'managedResourceTypes': [],
                'resourceTemplates': []
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={}
        )
        att = saasherder._get_saas_file_feature_enabled(
            'no_such_att', default=True)
        self.assertEqual(att, True)

    def test_attribute_not_none_with_default(self):
        saas_files = [
            {
                'path': 'path1',
                'name': 'name1',
                'managedResourceTypes': [],
                'resourceTemplates': [],
                'attrib': True
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={}
        )
        att = saasherder._get_saas_file_feature_enabled(
            'attrib', default=False)
        self.assertEqual(att, True)

    def test_attribute_multiple_saas_files_return_false(self):
        saas_files = [
            {
                'path': 'path1',
                'name': 'name1',
                'managedResourceTypes': [],
                'resourceTemplates': [],
                'attrib': True
            },
            {
                'path': 'path2',
                'name': 'name2',
                'managedResourceTypes': [],
                'resourceTemplates': []
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={}
        )
        self.assertFalse(saasherder._get_saas_file_feature_enabled('attrib'))

    def test_attribute_multiple_saas_files_with_default_return_false(self):
        saas_files = [
            {
                'path': 'path1',
                'name': 'name1',
                'managedResourceTypes': [],
                'resourceTemplates': [],
                'attrib': True
            },
            {
                'path': 'path2',
                'name': 'name2',
                'managedResourceTypes': [],
                'resourceTemplates': [],
                'attrib': True
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            settings={}
        )
        att = saasherder._get_saas_file_feature_enabled(
            'attrib', default=True)
        self.assertFalse(att)
