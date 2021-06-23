from unittest import TestCase

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
                'name': 'long-name-which-is-too-long-to-produce-unique-combo',
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
