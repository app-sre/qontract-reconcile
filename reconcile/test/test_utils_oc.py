from unittest import TestCase
from unittest.mock import patch, MagicMock, PropertyMock

from reconcile.utils.oc import OC, PodNotReadyError


class TestGetOwnedPods(TestCase):
    @patch.object(OC, 'get')
    @patch.object(OC, 'get_obj_root_owner')
    def test_get_owned_pods(self, oc_get_obj_root_owner, oc_get):

        oc_get.return_value = {
            'items': [
                {
                    'metadata': {
                        'name': 'pod1',
                        'ownerReferences': [
                            {
                                'controller': True,
                                'kind': 'ownerkind',
                                'name': 'ownername'
                            }
                        ]
                    }
                },
                {
                    'metadata': {
                        'name': 'pod2',
                        'ownerReferences': [
                            {
                                'controller': True,
                                'kind': 'notownerkind',
                                'name': 'notownername'
                            }
                        ]
                    }
                },
                {
                    'metadata': {
                        'name': 'pod3',
                        'ownerReferences': [
                            {
                                'controller': True,
                                'kind': 'ownerkind',
                                'name': 'notownername'
                            }
                        ]
                    }
                },
            ]
        }
        oc_get_obj_root_owner.side_effect = [
            {
                'kind': 'ownerkind',
                'metadata': {'name': 'ownername'}
            },
            {
                'kind': 'notownerkind',
                'metadata': {'name': 'notownername'},
            },
            {
                'kind': 'ownerkind',
                'metadata': {'name': 'notownername'}
            }
        ]

        resource = MagicMock(kind='ownerkind')
        # a PropertyMock representing the 'name' attribute
        type(resource).name = PropertyMock(return_value='ownername')

        oc = OC('server', 'token', local=True)
        pods = oc.get_owned_pods('namespace', resource)
        self.assertEqual(len(pods), 1)
        self.assertEqual(pods[0]['metadata']['name'], 'pod1')


class TestValidatePodReady(TestCase):
    @staticmethod
    @patch.object(OC, 'get')
    def test_validate_pod_ready_all_good(oc_get):
        oc_get.return_value = {
            'status': {
                'containerStatuses': [
                    {
                        'name': 'container1',
                        'ready': True,
                    },
                    {
                        'name': 'container2',
                        'ready': True
                    }
                ]
            }
        }
        oc = OC('server', 'token', local=True)
        oc.validate_pod_ready('namespace', 'podname')

    @patch.object(OC, 'get')
    def test_validate_pod_ready_one_missing(self, oc_get):
        oc_get.return_value = {
            'status': {
                'containerStatuses': [
                    {
                        'name': 'container1',
                        'ready': True,
                    },
                    {
                        'name': 'container2',
                        'ready': False
                    }
                ]
            }
        }

        oc = OC('server', 'token', local=True)
        with self.assertRaises(PodNotReadyError):
            # Bypass the retry stuff
            oc.validate_pod_ready.__wrapped__(oc, 'namespace', 'podname')
