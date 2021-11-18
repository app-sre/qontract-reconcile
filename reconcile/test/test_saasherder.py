import copy
from unittest import TestCase
from unittest.mock import patch, MagicMock

import yaml

from github import GithubException
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.saasherder import PARENT_CONFIG_HASH_ATTR

from .fixtures import Fixtures

fxt = Fixtures('saasherder')


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
                'configurable_resources': False,
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
                'configurable_resources': False,
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
        self.fxts = Fixtures('saasherder_populate_desired')
        for file in [self.fxts.get("saas_remote_openshift_template.yaml")]:
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

        # Mock GitHub interactions.
        self.initiate_gh_patcher = patch.object(
            SaasHerder, '_initiate_github', autospec=True, return_value=None,
        )
        self.get_file_contents_patcher = patch.object(
            SaasHerder,
            '_get_file_contents',
            wraps=self.fake_get_file_contents,
        )
        self.initiate_gh_patcher.start()
        self.get_file_contents_patcher.start()

        # Mock image checking.
        self.get_check_images_patcher = patch.object(
            SaasHerder,
            '_check_images',
            autospec=True,
            return_value=None,
        )
        self.get_check_images_patcher.start()

    def fake_get_file_contents(self, options):
        self.assertEqual(
            'https://github.com/rhobs/configuration', options['url'])

        content = self.fxts.get(
            options['ref'] + (options['path'].replace('/', '_')))
        return yaml.safe_load(content), "yolo", options['ref']

    def tearDown(self):
        for p in (
            self.initiate_gh_patcher,
            self.get_file_contents_patcher,
            self.get_check_images_patcher,
        ):
            p.stop()

    def test_populate_desired_state_saas_file_delete(self):
        spec = {'delete': True}

        desired_state \
            = self.saasherder.populate_desired_state_saas_file(spec, None)
        self.assertIsNone(desired_state)

    def test_populate_desired_state_cases(self):
        ri = ResourceInventory()
        for resource_type in (
                "Deployment",
                "Service",
                "ConfigMap",
        ):
            ri.initialize_resource_type("stage-1", "yolo-stage", resource_type)
            ri.initialize_resource_type("prod-1", "yolo", resource_type)
        self.saasherder.populate_desired_state(ri)

        cnt = 0
        for (cluster, namespace, resource_type, data) in ri:
            for _, d_item in data['desired'].items():
                expected = yaml.safe_load(self.fxts.get(
                        f"expected_{cluster}_{namespace}_{resource_type}.json",
                ))
                self.assertEqual(expected,  d_item.body)
                cnt += 1

        self.assertEqual(5, cnt, "expected 5 resources, found less")


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


class TestGetConfigDiffs(TestCase):

    cluster = "test-cluster"
    namespace = "test-namespace"

    def setUp(self) -> None:
        state_patcher = \
            patch("reconcile.utils.saasherder.State", autospec=True)
        self.state_mock = state_patcher.start().return_value

        ig_patcher = \
            patch.object(SaasHerder, "_initiate_github", autospec=True)
        ig_patcher.start()

        gfc_patcher = \
            patch.object(SaasHerder, "_get_file_contents", autospec=True)
        gfc_mock = gfc_patcher.start()

        self.saas_file = fxt.get_anymarkup('saas_file_deployment.yml')
        template = fxt.get_anymarkup('template_1.yml')
        gfc_mock.return_value = (template, "url", "ahash")

        self.ri = ResourceInventory()
        for kind in ["Service", "Deployment"]:
            self.ri.initialize_resource_type(
                self.cluster, self.namespace, kind)

        self.saasherder = SaasHerder(
            [self.saas_file],
            thread_pool_size=1,
            gitlab=None,
            integration='',
            integration_version='',
            accounts={"name": "test-account"},  # Initiates State in SaasHerder
            settings={}
        )

        self.saasherder.populate_desired_state(self.ri)

        if self.ri.has_error_registered():
            raise Exception("Errors registered in Resourceinventory")

    def test_config_hash_is_filled(self):
        job_spec = \
            self.saasherder.get_configs_diff_saas_file(self.saas_file)[0]
        promotion = job_spec["target_config"]["promotion"]
        self.assertIsNotNone(promotion[PARENT_CONFIG_HASH_ATTR])

    def test_same_configs_do_not_trigger(self):
        configs = \
            self.saasherder.get_saas_targets_config(self.saas_file)

        desired_tc = list(configs.values())[0]
        self.state_mock.get.return_value = desired_tc

        job_specs = \
            self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertListEqual(job_specs, [])

    def test_config_hash_change_do_trigger(self):
        configs = \
            self.saasherder.get_saas_targets_config(self.saas_file)

        desired_tc = list(configs.values())[0]
        current_tc = copy.deepcopy(desired_tc)
        current_tc["promotion"][PARENT_CONFIG_HASH_ATTR] = "old_hash"

        self.state_mock.get.return_value = current_tc
        job_specs = \
            self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertEqual(len(job_specs), 1)

    def test_add_config_hash_do_trigger(self):
        configs = \
            self.saasherder.get_saas_targets_config(self.saas_file)

        desired_tc = list(configs.values())[0]
        current_tc = copy.deepcopy(desired_tc)
        del(current_tc["promotion"][PARENT_CONFIG_HASH_ATTR])

        self.state_mock.get.return_value = current_tc
        job_specs = \
            self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertEqual(len(job_specs), 1)

    def test_promotion_state_config_hash_match_validates(self):
        configs = \
            self.saasherder.get_saas_targets_config(self.saas_file)

        desired_tc = list(configs.values())[0]
        promotion = desired_tc['promotion']
        promotion_result = {
            "success": True,
            PARENT_CONFIG_HASH_ATTR: promotion[PARENT_CONFIG_HASH_ATTR]
        }
        self.state_mock.get.return_value = promotion_result
        result = self.saasherder.validate_promotions()
        self.assertTrue(result)

    def test_promotion_state_config_hash_not_match_no_validates(self):
        configs = \
            self.saasherder.get_saas_targets_config(self.saas_file)

        desired_tc = list(configs.values())[0]
        promotion = desired_tc['promotion']
        promotion_result = {
            "success": True,
            PARENT_CONFIG_HASH_ATTR: "will_not_match"
        }
        self.state_mock.get.return_value = promotion_result
        result = self.saasherder.validate_promotions()
        self.assertFalse(result)

    def test_promotion_without_state_config_hash_validates(self):
        promotion_result = {
            "success": True,
        }
        self.state_mock.get.return_value = promotion_result
        result = self.saasherder.validate_promotions()
        self.assertFalse(result)