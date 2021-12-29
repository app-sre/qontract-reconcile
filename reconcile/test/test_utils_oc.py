import os
from unittest import TestCase
from unittest.mock import patch

import reconcile.utils.oc
from reconcile.utils.oc import (
    LABEL_MAX_KEY_NAME_LENGTH, LABEL_MAX_KEY_PREFIX_LENGTH,
    LABEL_MAX_VALUE_LENGTH,
    OC, OCDeprecated, PodNotReadyError, StatusCodeError, validate_labels,
    OC_Map, OCLogMsg)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.secret_reader import SecretReader, SecretNotFound


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
    def test_controller_false_return_controller(self, oc_get):
        """Returns owner if all ownerReferences have controller set to false
        and allow_not_controller is set to True
        """
        obj = {
            'metadata': {
                'name': 'pod1',
                'ownerReferences': [
                    {
                        'controller': False,
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
        result_obj = oc.get_obj_root_owner('namespace', obj,
                                           allow_not_controller=True)
        self.assertEqual(result_obj, owner_obj)

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


class TestPodOwnedPVCNames(TestCase):
    def setUp(self):
        self.oc = OC('cluster', 'server', 'token', local=True)

    def test_no_volumes(self):
        pods = [{'volumes': []}]
        owned_pvc_names = self.oc.get_pod_owned_pvc_names(pods)
        self.assertEqual(len(owned_pvc_names), 0)

    def test_other_volumes(self):
        pods = [{'volumes': [{'configMap': {'name': 'cm'}}]}]
        owned_pvc_names = self.oc.get_pod_owned_pvc_names(pods)
        self.assertEqual(len(owned_pvc_names), 0)

    def test_ok(self):
        pods = [{'volumes': [{'persistentVolumeClaim': {'claimName': 'cm'}}]}]
        owned_pvc_names = self.oc.get_pod_owned_pvc_names(pods)
        self.assertEqual(len(owned_pvc_names), 1)
        self.assertEqual(owned_pvc_names[0], 'cm')


class TestGetStorage(TestCase):
    def setUp(self):
        self.oc = OC('cluster', 'server', 'token', local=True)

    def test_none(self):
        resource = {'spec': 'whatever'}
        storage = self.oc.get_storage(resource)
        self.assertIsNone(storage)

    def test_ok(self):
        size = "100Gi"
        resource = {
            'spec': {
                'volumeClaimTemplates': [
                    {
                        'spec': {
                            'resources': {
                                'requests': {
                                    'storage': size
                                }
                            }
                        }
                    }
                ]
            }
        }
        result = self.oc.get_storage(resource)
        self.assertEqual(result, size)


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


class TestOCMapInit(TestCase):

    def test_missing_serverurl(self):
        """
        When a cluster with a missing serverUrl is passed into OC_Map, it
        should be skipped.
        """
        cluster = {
            'name': 'test-1',
            'serverUrl': '',
            'automationToken': {
                'path': 'some-path',
                'field': 'some-field'
            }
        }
        oc_map = OC_Map(clusters=[cluster])

        self.assertIsInstance(oc_map.get(cluster['name']), OCLogMsg)
        self.assertEqual(oc_map.get(cluster['name']).message,
                         f'[{cluster["name"]}] has no serverUrl')
        self.assertEqual(len(oc_map.clusters()), 0)

    def test_missing_automationtoken(self):
        """
        When a cluster with a missing automationToken is passed into OC_Map, it
        should be skipped.
        """
        cluster = {
            'name': 'test-1',
            'serverUrl': 'http://localhost',
            'automationToken': None
        }
        oc_map = OC_Map(clusters=[cluster])

        self.assertIsInstance(oc_map.get(cluster['name']), OCLogMsg)
        self.assertEqual(oc_map.get(cluster['name']).message,
                         f'[{cluster["name"]}] has no automation token')
        self.assertEqual(len(oc_map.clusters()), 0)

    @patch.object(SecretReader, 'read', autospec=True)
    def test_automationtoken_not_found(self, mock_secret_reader):

        mock_secret_reader.side_effect = SecretNotFound

        cluster = {
            'name': 'test-1',
            'serverUrl': 'http://localhost',
            'automationToken': {
                'path': 'some-path',
                'field': 'some-field'
            }
        }

        oc_map = OC_Map(clusters=[cluster])

        self.assertIsInstance(oc_map.get(cluster['name']), OCLogMsg)
        self.assertEqual(oc_map.get(cluster['name']).message,
                         f'[{cluster["name"]}] secret not found')
        self.assertEqual(len(oc_map.clusters()), 0)


class TestOCMapGetClusters(TestCase):
    @patch.object(SecretReader, 'read', autospec=True)
    def test_clusters_errors_empty_return(self, mock_secret_reader):
        """
        clusters() shouldn't return the names of any clusters that didn't
        initialize a client successfully.
        """
        cluster = {
            'name': 'test-1',
            'serverUrl': 'http://localhost',
        }

        oc_map = OC_Map(clusters=[cluster])

        self.assertEqual(oc_map.clusters(), [])
        self.assertIsInstance(oc_map.oc_map.get(cluster['name']), OCLogMsg)

    @patch.object(reconcile.utils.oc, 'OC', autospec=True)
    @patch.object(SecretReader, 'read', autospec=True)
    def test_clusters_errors_with_include_errors(
            self, mock_secret_reader, mock_oc):
        """
        With the include_errors kwarg set to true, clusters that didn't
        initialize a client are still included.
        """
        cluster_1 = {
            'name': 'test-1',
            'serverUrl': 'http://localhost',
        }

        cluster_2 = {
            'name': 'test-2',
            'serverUrl': 'http://localhost',
            'automationToken': {
                'path': 'some-path',
                'field': 'some-field'
            }
        }

        cluster_names = [cluster_1['name'], cluster_2['name']]

        oc_map = OC_Map(clusters=[cluster_1, cluster_2])

        self.assertEqual(oc_map.clusters(include_errors=True), cluster_names)
        self.assertIsInstance(oc_map.oc_map.get(cluster_1['name']), OCLogMsg)
