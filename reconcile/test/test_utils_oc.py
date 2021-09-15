import os
from unittest import TestCase
from unittest.mock import patch

from reconcile.utils.oc import (
    LABEL_MAX_KEY_NAME_LENGTH, LABEL_MAX_KEY_PREFIX_LENGTH,
    LABEL_MAX_VALUE_LENGTH,
    OC, OCDeprecated, PodNotReadyError, StatusCodeError, validate_labels)
from reconcile.utils.openshift_resource import OpenshiftResource as OR


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
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


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
class TestValidatePodReady(TestCase):
    @patch.object(OCDeprecated, 'get')
    # pylint: disable=no-self-use
    def test_validate_pod_ready_all_good(self, oc_get):
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


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
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


class TestValidateLabels(TestCase):
    def test_ok(self):
        self.assertFalse(validate_labels({'my.company.com/key-name': 'value'}))

    def test_long_value(self):
        v = 'a' * LABEL_MAX_VALUE_LENGTH
        self.assertFalse(validate_labels({'my.company.com/key-name': v}))

        v = 'a' * (LABEL_MAX_VALUE_LENGTH + 1)
        r = validate_labels({'my.company.com/key-name': v})
        self.assertEqual(len(r), 1)

    def test_long_keyname(self):
        kn = 'a' * LABEL_MAX_KEY_NAME_LENGTH
        self.assertFalse(validate_labels({f'my.company.com/{kn}': 'value'}))

        kn = 'a' * (LABEL_MAX_KEY_NAME_LENGTH + 1)
        r = validate_labels({f'my.company.com/{kn}': 'value'})
        self.assertEqual(len(r), 1)

    def test_long_key_prefix(self):
        prefix = 'a' * LABEL_MAX_KEY_PREFIX_LENGTH
        self.assertFalse(validate_labels({f'{prefix}/key': 'value'}))

        prefix = 'a' * (LABEL_MAX_KEY_PREFIX_LENGTH + 1)
        r = validate_labels({f'{prefix}/key': 'value'})
        self.assertEqual(len(r), 1)

    def test_invalid_value(self):
        r = validate_labels({'my.company.com/key-name': 'b@d'})
        self.assertEqual(len(r), 1)

    def test_invalid_key_name(self):
        r = validate_labels({'my.company.com/key@name': 'value'})
        self.assertEqual(len(r), 1)

    def test_invalid_key_prefix(self):
        r = validate_labels({'my@company.com/key-name': 'value'})
        self.assertEqual(len(r), 1)

    def test_reserved_key_prefix(self):
        r = validate_labels({'kubernetes.io/key-name': 'value'})
        self.assertEqual(len(r), 1)

        r = validate_labels({'k8s.io/key-name': 'value'})
        self.assertEqual(len(r), 1)

    def test_many_wrong(self):
        longstr = 'a' * (LABEL_MAX_KEY_PREFIX_LENGTH + 1)
        key_prefix = 'b@d.' + longstr + '.com'
        key_name = 'b@d-' + longstr
        value = 'b@d-' + longstr
        r = validate_labels({
            f'{key_prefix}/{key_name}': value,
            'kubernetes.io/b@d': value})
        self.assertEqual(len(r), 10)
