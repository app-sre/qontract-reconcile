from unittest import TestCase
from unittest.mock import patch

from reconcile.utils.oc import (
    OC, OCDeprecated, PodNotReadyError, StatusCodeError)
from reconcile.utils.openshift_resource import OpenshiftResource as OR


class TestGetOwnedPods(TestCase):
    @patch.object(OCDeprecated, 'get')
    @patch.object(OCDeprecated, 'get_obj_root_owner')
    def test_get_owned_pods(self, oc_get_obj_root_owner, oc_get):
        owner_body = {
            'kind': 'ownerkind',
            'metadata': {'name': 'ownername'}
        }
        owner_resource = OR(owner_body, '', '')

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
            owner_resource.body,
            {
                'kind': 'notownerkind',
                'metadata': {'name': 'notownername'},
            },
            {
                'kind': 'ownerkind',
                'metadata': {'name': 'notownername'}
            }
        ]

        oc = OC('cluster', 'server', 'token', local=True)
        pods = oc.get_owned_pods('namespace', owner_resource)
        self.assertEqual(len(pods), 1)
        self.assertEqual(pods[0]['metadata']['name'], 'pod1')


class TestValidatePodReady(TestCase):
    @staticmethod
    @patch.object(OCDeprecated, 'get')
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
        oc = OC('cluster', 'server', 'token', local=True)
        oc.validate_pod_ready('namespace', 'podname')

    @patch.object(OCDeprecated, 'get')
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

        oc = OC('cluster', 'server', 'token', local=True)
        with self.assertRaises(PodNotReadyError):
            # Bypass the retry stuff
            oc.validate_pod_ready.__wrapped__(oc, 'namespace', 'podname')


class TestGetObjRootOwner(TestCase):
    @patch.object(OCDeprecated, 'get')
    def test_owner(self, oc_get):
        obj = {
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
        }
        owner_obj = {
            'kind': 'ownerkind',
            'metadata': {'name': 'ownername'}
        }

        oc_get.side_effect = [
            owner_obj
        ]

        oc = OC('cluster', 'server', 'token', local=True)
        result_owner_obj = oc.get_obj_root_owner('namespace', obj)
        self.assertEqual(result_owner_obj, owner_obj)

    def test_no_owner(self):
        obj = {
            'metadata': {
                'name': 'pod1',
            }
        }

        oc = OC('cluster', 'server', 'token', local=True)
        result_obj = oc.get_obj_root_owner('namespace', obj)
        self.assertEqual(result_obj, obj)

    def test_controller_false_return_obj(self):
        """Returns obj if all ownerReferences have controller set to false
        """
        obj = {
            'metadata': {
                'name': 'pod1',
                'ownerReferences': [
                    {
                        'controller': False
                    }
                ]
            }
        }

        oc = OC('cluster', 'server', 'token', local=True)
        result_obj = oc.get_obj_root_owner('namespace', obj)
        self.assertEqual(result_obj, obj)

    @patch.object(OCDeprecated, 'get')
    def test_cont_true_allow_true_ref_not_found_return_obj(self, oc_get):
        """Returns obj if controller is true, allow_not_found is true,
        but referenced object does not exist '{}'
        """
        obj = {
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
        }
        owner_obj = {}

        oc_get.side_effect = [
            owner_obj
        ]

        oc = OC('cluster', 'server', 'token', local=True)
        result_obj = oc.get_obj_root_owner('namespace', obj,
                                           allow_not_found=True)
        self.assertEqual(result_obj, obj)

    @patch.object(OCDeprecated, 'get')
    def test_controller_true_allow_false_ref_not_found_raise(self, oc_get):
        """Throws an exception if controller is true, allow_not_found false,
        but referenced object does not exist
        """
        obj = {
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
        }

        oc_get.side_effect = StatusCodeError

        oc = OC('cluster', 'server', 'token', local=True)
        with self.assertRaises(StatusCodeError):
            oc.get_obj_root_owner('namespace', obj, allow_not_found=False)
