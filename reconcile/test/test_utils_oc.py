import logging
import os
from unittest import TestCase
from unittest.mock import patch

import pytest
from kubernetes.dynamic import Resource
from kubernetes.dynamic.exceptions import ResourceNotFoundError

import reconcile.utils.oc
from reconcile.utils.oc import (
    GET_REPLICASET_MAX_ATTEMPTS,
    LABEL_MAX_KEY_NAME_LENGTH,
    LABEL_MAX_KEY_PREFIX_LENGTH,
    LABEL_MAX_VALUE_LENGTH,
    OC,
    OC_Map,
    OCCli,
    OCLogMsg,
    OCNative,
    PodNotReadyError,
    StatusCodeError,
    equal_spec_template,
    validate_labels,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.secret_reader import (
    SecretNotFound,
    SecretReader,
)


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
class TestGetOwnedPods(TestCase):
    @patch.object(OCCli, "get")
    @patch.object(OCCli, "get_obj_root_owner")
    def test_get_owned_pods(self, oc_get_obj_root_owner, oc_get):
        owner_body = {"kind": "ownerkind", "metadata": {"name": "ownername"}}
        owner_resource = OR(owner_body, "", "")

        oc_get.return_value = {
            "items": [
                {
                    "metadata": {
                        "name": "pod1",
                        "ownerReferences": [
                            {
                                "controller": True,
                                "kind": "ownerkind",
                                "name": "ownername",
                            }
                        ],
                    }
                },
                {
                    "metadata": {
                        "name": "pod2",
                        "ownerReferences": [
                            {
                                "controller": True,
                                "kind": "notownerkind",
                                "name": "notownername",
                            }
                        ],
                    }
                },
                {
                    "metadata": {
                        "name": "pod3",
                        "ownerReferences": [
                            {
                                "controller": True,
                                "kind": "ownerkind",
                                "name": "notownername",
                            }
                        ],
                    }
                },
            ]
        }
        oc_get_obj_root_owner.side_effect = [
            owner_resource.body,
            {
                "kind": "notownerkind",
                "metadata": {"name": "notownername"},
            },
            {"kind": "ownerkind", "metadata": {"name": "notownername"}},
        ]

        oc = OC("cluster", "server", "token", local=True)
        pods = oc.get_owned_pods("namespace", owner_resource)
        self.assertEqual(len(pods), 1)
        self.assertEqual(pods[0]["metadata"]["name"], "pod1")


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
class TestValidatePodReady(TestCase):
    @patch.object(OCCli, "get")
    def test_validate_pod_ready_all_good(self, oc_get):
        oc_get.return_value = {
            "status": {
                "containerStatuses": [
                    {
                        "name": "container1",
                        "ready": True,
                    },
                    {"name": "container2", "ready": True},
                ]
            }
        }
        oc = OC("cluster", "server", "token", local=True)
        oc.validate_pod_ready("namespace", "podname")

    @patch.object(OCCli, "get")
    def test_validate_pod_ready_one_missing(self, oc_get):
        oc_get.return_value = {
            "status": {
                "containerStatuses": [
                    {
                        "name": "container1",
                        "ready": True,
                    },
                    {"name": "container2", "ready": False},
                ]
            }
        }

        oc = OC("cluster", "server", "token", local=True)
        with self.assertRaises(PodNotReadyError):
            # Bypass the retry stuff
            oc.validate_pod_ready.__wrapped__(oc, "namespace", "podname")


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
class TestGetObjRootOwner(TestCase):
    @patch.object(OCCli, "get")
    def test_owner(self, oc_get):
        obj = {
            "metadata": {
                "name": "pod1",
                "ownerReferences": [
                    {"controller": True, "kind": "ownerkind", "name": "ownername"}
                ],
            }
        }
        owner_obj = {"kind": "ownerkind", "metadata": {"name": "ownername"}}

        oc_get.side_effect = [owner_obj]

        oc = OC("cluster", "server", "token", local=True)
        result_owner_obj = oc.get_obj_root_owner("namespace", obj)
        self.assertEqual(result_owner_obj, owner_obj)

    def test_no_owner(self):
        obj = {
            "metadata": {
                "name": "pod1",
            }
        }

        oc = OC("cluster", "server", "token", local=True)
        result_obj = oc.get_obj_root_owner("namespace", obj)
        self.assertEqual(result_obj, obj)

    def test_controller_false_return_obj(self):
        """Returns obj if all ownerReferences have controller set to false"""
        obj = {"metadata": {"name": "pod1", "ownerReferences": [{"controller": False}]}}

        oc = OC("cluster", "server", "token", local=True)
        result_obj = oc.get_obj_root_owner("namespace", obj)
        self.assertEqual(result_obj, obj)

    @patch.object(OCCli, "get")
    def test_controller_false_return_controller(self, oc_get):
        """Returns owner if all ownerReferences have controller set to false
        and allow_not_controller is set to True
        """
        obj = {
            "metadata": {
                "name": "pod1",
                "ownerReferences": [
                    {"controller": False, "kind": "ownerkind", "name": "ownername"}
                ],
            }
        }
        owner_obj = {"kind": "ownerkind", "metadata": {"name": "ownername"}}
        oc_get.side_effect = [owner_obj]

        oc = OC("cluster", "server", "token", local=True)
        result_obj = oc.get_obj_root_owner("namespace", obj, allow_not_controller=True)
        self.assertEqual(result_obj, owner_obj)

    @patch.object(OCCli, "get")
    def test_cont_true_allow_true_ref_not_found_return_obj(self, oc_get):
        """Returns obj if controller is true, allow_not_found is true,
        but referenced object does not exist '{}'
        """
        obj = {
            "metadata": {
                "name": "pod1",
                "ownerReferences": [
                    {"controller": True, "kind": "ownerkind", "name": "ownername"}
                ],
            }
        }
        owner_obj = {}

        oc_get.side_effect = [owner_obj]

        oc = OC("cluster", "server", "token", local=True)
        result_obj = oc.get_obj_root_owner("namespace", obj, allow_not_found=True)
        self.assertEqual(result_obj, obj)

    @patch.object(OCCli, "get")
    def test_controller_true_allow_false_ref_not_found_raise(self, oc_get):
        """Throws an exception if controller is true, allow_not_found false,
        but referenced object does not exist
        """
        obj = {
            "metadata": {
                "name": "pod1",
                "ownerReferences": [
                    {"controller": True, "kind": "ownerkind", "name": "ownername"}
                ],
            }
        }

        oc_get.side_effect = StatusCodeError

        oc = OC("cluster", "server", "token", local=True)
        with self.assertRaises(StatusCodeError):
            oc.get_obj_root_owner("namespace", obj, allow_not_found=False)


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
class TestPodOwnedPVCNames(TestCase):
    def test_no_volumes(self):
        pods = [{"spec": {"volumes": []}}]
        oc = OC("cluster", "server", "token", local=True)
        owned_pvc_names = oc.get_pod_owned_pvc_names(pods)
        self.assertEqual(len(owned_pvc_names), 0)

    def test_other_volumes(self):
        pods = [{"spec": {"volumes": [{"configMap": {"name": "cm"}}]}}]
        oc = OC("cluster", "server", "token", local=True)
        owned_pvc_names = oc.get_pod_owned_pvc_names(pods)
        self.assertEqual(len(owned_pvc_names), 0)

    def test_ok(self):
        pods = [{"spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "cm"}}]}}]
        oc = OC("cluster", "server", "token", local=True)
        owned_pvc_names = oc.get_pod_owned_pvc_names(pods)
        self.assertEqual(len(owned_pvc_names), 1)
        self.assertEqual(list(owned_pvc_names)[0], "cm")


@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "False"}, clear=True)
class TestGetStorage(TestCase):
    def test_none(self):
        resource = {"spec": {"what": "ever"}}
        oc = OC("cluster", "server", "token", local=True)
        storage = oc.get_storage(resource)
        self.assertIsNone(storage)

    def test_ok(self):
        size = "100Gi"
        resource = {
            "spec": {
                "volumeClaimTemplates": [
                    {"spec": {"resources": {"requests": {"storage": size}}}}
                ]
            }
        }
        oc = OC("cluster", "server", "token", local=True)
        result = oc.get_storage(resource)
        self.assertEqual(result, size)


class TestValidateLabels(TestCase):
    def test_ok(self):
        self.assertFalse(validate_labels({"my.company.com/key-name": "value"}))

    def test_long_value(self):
        v = "a" * LABEL_MAX_VALUE_LENGTH
        self.assertFalse(validate_labels({"my.company.com/key-name": v}))

        v = "a" * (LABEL_MAX_VALUE_LENGTH + 1)
        r = validate_labels({"my.company.com/key-name": v})
        self.assertEqual(len(r), 1)

    def test_long_keyname(self):
        kn = "a" * LABEL_MAX_KEY_NAME_LENGTH
        self.assertFalse(validate_labels({f"my.company.com/{kn}": "value"}))

        kn = "a" * (LABEL_MAX_KEY_NAME_LENGTH + 1)
        r = validate_labels({f"my.company.com/{kn}": "value"})
        self.assertEqual(len(r), 1)

    def test_long_key_prefix(self):
        prefix = "a" * LABEL_MAX_KEY_PREFIX_LENGTH
        self.assertFalse(validate_labels({f"{prefix}/key": "value"}))

        prefix = "a" * (LABEL_MAX_KEY_PREFIX_LENGTH + 1)
        r = validate_labels({f"{prefix}/key": "value"})
        self.assertEqual(len(r), 1)

    def test_invalid_value(self):
        r = validate_labels({"my.company.com/key-name": "b@d"})
        self.assertEqual(len(r), 1)

    def test_invalid_key_name(self):
        r = validate_labels({"my.company.com/key@name": "value"})
        self.assertEqual(len(r), 1)

    def test_invalid_key_prefix(self):
        r = validate_labels({"my@company.com/key-name": "value"})
        self.assertEqual(len(r), 1)

    def test_reserved_key_prefix(self):
        r = validate_labels({"kubernetes.io/key-name": "value"})
        self.assertEqual(len(r), 1)

        r = validate_labels({"k8s.io/key-name": "value"})
        self.assertEqual(len(r), 1)

    def test_many_wrong(self):
        longstr = "a" * (LABEL_MAX_KEY_PREFIX_LENGTH + 1)
        key_prefix = "b@d." + longstr + ".com"
        key_name = "b@d-" + longstr
        value = "b@d-" + longstr
        r = validate_labels(
            {f"{key_prefix}/{key_name}": value, "kubernetes.io/b@d": value}
        )
        self.assertEqual(len(r), 10)


class TestOCMapInit(TestCase):
    def test_missing_serverurl(self):
        """
        When a cluster with a missing serverUrl is passed into OC_Map, it
        should be skipped.
        """
        cluster = {
            "name": "test-1",
            "serverUrl": "",
            "automationToken": {"path": "some-path", "field": "some-field"},
        }
        oc_map = OC_Map(clusters=[cluster])

        self.assertIsInstance(oc_map.get(cluster["name"]), OCLogMsg)
        self.assertEqual(
            oc_map.get(cluster["name"]).message, f'[{cluster["name"]}] has no serverUrl'
        )
        self.assertEqual(len(oc_map.clusters()), 0)

    def test_missing_automationtoken(self):
        """
        When a cluster with a missing automationToken is passed into OC_Map, it
        should be skipped.
        """
        cluster = {
            "name": "test-1",
            "serverUrl": "http://localhost",
            "automationToken": None,
        }
        oc_map = OC_Map(clusters=[cluster])

        self.assertIsInstance(oc_map.get(cluster["name"]), OCLogMsg)
        self.assertEqual(
            oc_map.get(cluster["name"]).message,
            f'[{cluster["name"]}] has no automation token',
        )
        self.assertEqual(len(oc_map.clusters()), 0)

    @patch.object(SecretReader, "read_all", autospec=True)
    def test_automationtoken_not_found(self, mock_secret_reader):
        mock_secret_reader.side_effect = SecretNotFound

        cluster = {
            "name": "test-1",
            "serverUrl": "http://localhost",
            "automationToken": {"path": "some-path", "field": "some-field"},
        }

        oc_map = OC_Map(clusters=[cluster])

        self.assertIsInstance(oc_map.get(cluster["name"]), OCLogMsg)
        self.assertEqual(
            oc_map.get(cluster["name"]).message, f'[{cluster["name"]}] secret not found'
        )
        self.assertEqual(len(oc_map.clusters()), 0)

    @patch.object(SecretReader, "read_all", autospec=True)
    def test_server_url_mismatch(self, mock_secret_reader):
        mock_secret_reader.return_value = {"server": "foo", "some-field": "bar"}

        cluster = {
            "name": "test-1",
            "serverUrl": "http://localhost",
            "automationToken": {"path": "some-path", "field": "some-field"},
        }

        oc_map = OC_Map(clusters=[cluster])

        self.assertIsInstance(oc_map.get(cluster["name"]), OCLogMsg)
        self.assertEqual(
            oc_map.get(cluster["name"]).message,
            f'[{cluster["name"]}] server URL mismatch',
        )
        self.assertEqual(len(oc_map.clusters()), 0)


class TestOCMapGetClusters(TestCase):
    @patch.object(SecretReader, "read_all", autospec=True)
    def test_clusters_errors_empty_return(self, mock_secret_reader):
        """
        clusters() shouldn't return the names of any clusters that didn't
        initialize a client successfully.
        """
        mock_secret_reader.return_value = {
            "server": "http://localhost",
            "some-field": "bar",
        }

        cluster = {
            "name": "test-1",
            "serverUrl": "http://localhost",
        }

        oc_map = OC_Map(clusters=[cluster])

        self.assertEqual(oc_map.clusters(), [])
        self.assertIsInstance(oc_map.oc_map.get(cluster["name"]), OCLogMsg)

    @patch.object(reconcile.utils.oc, "OC", autospec=True)
    @patch.object(SecretReader, "read_all", autospec=True)
    def test_clusters_errors_with_include_errors(self, mock_secret_reader, mock_oc):
        """
        With the include_errors kwarg set to true, clusters that didn't
        initialize a client are still included.
        """
        mock_secret_reader.return_value = {
            "server": "http://localhost",
            "some-field": "bar",
        }

        cluster_1 = {
            "name": "test-1",
            "serverUrl": "http://localhost",
        }

        cluster_2 = {
            "name": "test-2",
            "serverUrl": "http://localhost",
            "automationToken": {"path": "some-path", "field": "some-field"},
        }

        cluster_names = [cluster_1["name"], cluster_2["name"]]

        oc_map = OC_Map(clusters=[cluster_1, cluster_2])

        self.assertEqual(oc_map.clusters(include_errors=True), cluster_names)
        self.assertIsInstance(oc_map.oc_map.get(cluster_1["name"]), OCLogMsg)

    @patch.object(reconcile.utils.oc, "OC", autospec=True)
    @patch.object(SecretReader, "read_all", autospec=True)
    def test_namespace_with_cluster_admin(self, mock_secret_reader, mock_oc):
        mock_secret_reader.return_value = {
            "server": "http://localhost",
            "some-field": "bar",
        }

        cluster_1 = {
            "name": "cl1",
            "serverUrl": "http://localhost",
            "clusterAdminAutomationToken": {"path": "some-path", "field": "some-field"},
            "automationToken": {"path": "some-path", "field": "some-field"},
        }
        cluster_2 = {
            "name": "cl2",
            "serverUrl": "http://localhost",
            "clusterAdminAutomationToken": {"path": "some-path", "field": "some-field"},
            "automationToken": {"path": "some-path", "field": "some-field"},
        }
        namespace_1 = {"name": "ns1", "clusterAdmin": True, "cluster": cluster_1}

        namespace_2 = {"name": "ns2", "cluster": cluster_2}

        oc_map = OC_Map(namespaces=[namespace_1, namespace_2])

        self.assertEqual(oc_map.clusters(), ["cl1", "cl2"])
        self.assertEqual(oc_map.clusters(privileged=True), ["cl1"])

        # both clusters are present as non privileged clusters in the map
        self.assertIsInstance(oc_map.get(cluster_1["name"]), OC)
        self.assertIsInstance(oc_map.get(cluster_2["name"]), OC)

        # only cluster_1 is present as privileged cluster in the map
        self.assertIsInstance(oc_map.get(cluster_1["name"], privileged=True), OC)
        self.assertIsInstance(oc_map.get(cluster_2["name"], privileged=True), OCLogMsg)

    @patch.object(reconcile.utils.oc, "OC", autospec=True)
    @patch.object(SecretReader, "read_all", autospec=True)
    def test_missing_cluster_automation_token(self, mock_secret_reader, mock_oc):
        mock_secret_reader.return_value = {
            "server": "http://localhost",
            "some-field": "bar",
        }

        cluster_1 = {
            "name": "cl1",
            "serverUrl": "http://localhost",
            "automationToken": {"path": "some-path", "field": "some-field"},
        }
        namespace_1 = {"name": "ns1", "clusterAdmin": True, "cluster": cluster_1}

        oc_map = OC_Map(namespaces=[namespace_1])

        # check that non-priv OC got instantiated but priv one not
        self.assertEqual(oc_map.clusters(), ["cl1"])
        self.assertEqual(oc_map.clusters(privileged=True), [])
        self.assertEqual(
            oc_map.clusters(include_errors=True, privileged=True), [cluster_1["name"]]
        )

        self.assertIsInstance(oc_map.get(cluster_1["name"]), OC)
        self.assertFalse(oc_map.get(cluster_1["name"], privileged=True))

    @patch.object(reconcile.utils.oc, "OC", autospec=True)
    @patch.object(SecretReader, "read_all", autospec=True)
    def test_internal_clusters(self, mock_secret_reader, mock_oc):
        mock_secret_reader.return_value = {
            "server": "http://localhost",
            "some-field": "bar",
        }

        cluster = {
            "name": "cl1",
            "serverUrl": "http://localhost",
            "internal": True,
            "automationToken": {"path": "some-path", "field": "some-field"},
        }
        namespace = {"name": "ns1", "cluster": cluster}

        # internal cluster must be in oc_map when internal is enabled
        internal_oc_map = OC_Map(internal=True, namespaces=[namespace])
        self.assertIsInstance(internal_oc_map.get(cluster["name"]), OC)

        # internal cluster must not be in oc_map when internal is disabled
        oc_map = OC_Map(internal=False, namespaces=[namespace])
        self.assertFalse(oc_map.get(cluster["name"]))

    @patch.object(reconcile.utils.oc, "OC", autospec=True)
    @patch.object(SecretReader, "read_all", autospec=True)
    def test_disabled_integration(self, mock_secret_reader, mock_oc):
        mock_secret_reader.return_value = {
            "server": "http://localhost",
            "some-field": "bar",
        }

        calling_int = "calling_integration"
        cluster = {
            "name": "cl1",
            "serverUrl": "http://localhost",
            "disable": {"integrations": [calling_int.replace("_", "-")]},
            "automationToken": {"path": "some-path", "field": "some-field"},
        }
        namespace = {"name": "ns1", "cluster": cluster}

        oc_map = OC_Map(integration=calling_int, namespaces=[namespace])
        self.assertFalse(oc_map.get(cluster["name"]))


@pytest.fixture
def oc_cli(monkeypatch) -> OCCli:
    monkeypatch.setenv("USE_NATIVE_CLIENT", "False")
    return OC("cluster", "server", "token", local=True)  # type: ignore[return-value]


@pytest.fixture
def pod():
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "pod1",
        },
        "spec": {
            "volumes": [
                {"secret": {"secretName": "secret1"}},
                {"configMap": {"name": "configmap1"}},
            ],
            "containers": [
                {
                    "envFrom": [
                        {
                            "secretRef": {"name": "secret2"},
                        },
                        {"configMapRef": {"name": "configmap2"}},
                    ],
                    "env": [
                        {
                            "valueFrom": {
                                "secretKeyRef": {"name": "secret3", "key": "secretkey3"}
                            }
                        },
                        {
                            "valueFrom": {
                                "configMapKeyRef": {
                                    "name": "configmap3",
                                    "key": "configmapkey3",
                                }
                            }
                        },
                    ],
                }
            ],
        },
    }


def test_get_resources_used_in_pod_spec_unsupported_kind(oc_cli):
    with pytest.raises(KeyError):
        oc_cli.get_resources_used_in_pod_spec({}, "Deployment")


def test_get_resources_used_in_pod_spec_secret(oc_cli, pod):
    expected = {"secret1": set(), "secret2": set(), "secret3": {"secretkey3"}}
    results = oc_cli.get_resources_used_in_pod_spec(pod["spec"], "Secret")
    assert results == expected


def test_get_resources_used_in_pod_spec_configmap(oc_cli, pod):
    expected = {
        "configmap1": set(),
        "configmap2": set(),
        "configmap3": {"configmapkey3"},
    }
    results = oc_cli.get_resources_used_in_pod_spec(pod["spec"], "ConfigMap")
    assert results == expected


def test_secret_used_in_pod_true(oc_cli, pod):
    result = oc_cli.secret_used_in_pod("secret1", pod)
    assert result is True


def test_secret_used_in_pod_false(oc_cli, pod):
    result = oc_cli.secret_used_in_pod("secret9999", pod)
    assert result is False


def test_configmap_used_in_pod_true(oc_cli, pod):
    result = oc_cli.configmap_used_in_pod("configmap1", pod)
    assert result is True


def test_configmap_used_in_pod_false(oc_cli, pod):
    result = oc_cli.configmap_used_in_pod("configmap9999", pod)
    assert result is False


def test_oc_map_exception_on_missing_cluster():
    cluster = {
        "name": "test-1",
        "serverUrl": "",
        "automationToken": {"path": "some-path", "field": "some-field"},
    }
    oc_map = OC_Map(clusters=[cluster])

    assert isinstance(oc_map.get(cluster["name"]), OCLogMsg)
    with pytest.raises(OCLogMsg) as ctx:
        oc_map.get_cluster(cluster["name"])

    assert ctx.value.message == "[test-1] has no serverUrl"
    assert ctx.value.log_level == logging.ERROR


@pytest.mark.parametrize(
    "t1, t2, expected",
    [
        # trivial examples
        ({"a": "b"}, {"a": "b"}, True),
        ({"a": "b", "c": "d"}, {"c": "d", "a": "b"}, True),
        ({"a": "b", "c": "d"}, {"a": "b"}, False),
        # w/o pod-template-hash
        (
            # t1
            {
                "metadata": {},
                "spec": {"containers": [{"command": ["foobar"], "image": "lalala"}]},
            },
            # t2
            {
                "metadata": {},
                "spec": {"containers": [{"command": ["foobar"], "image": "lalala"}]},
            },
            # expected
            True,
        ),
        (
            # t1
            {
                "metadata": {},
                "spec": {"containers": [{"command": ["foobar"], "image": "lalala"}]},
            },
            # t2
            {
                "metadata": {},
                "spec": {
                    "containers": [{"command": ["something else"], "image": "lalala"}]
                },
            },
            # expected
            False,
        ),
        # with pod-template-hash
        (
            # t1
            {
                "metadata": {
                    "labels": {"a": "b", "pod-template-hash": "lala"},
                },
                "spec": {"containers": [{"command": ["foobar"], "image": "lalala"}]},
            },
            # t2
            {
                "metadata": {"labels": {"a": "b"}},
                "spec": {"containers": [{"command": ["foobar"], "image": "lalala"}]},
            },
            # expected
            True,
        ),
    ],
)
def test_equal_spec_template(t1, t2, expected):
    assert equal_spec_template(t1, t2) == expected


@pytest.fixture()
def deployment():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "annotations": {"qontract.update": "2022-07-12T09:15:14"},
            "creationTimestamp": "2022-07-12T07:36:50Z",
            "generation": 5,
            "name": "busybox",
        },
        "spec": {
            "replicas": 2,
            "selector": {"matchLabels": {"deployment": "busybox"}},
            "strategy": {
                "rollingUpdate": {"maxSurge": "25%", "maxUnavailable": "25%"},
                "type": "RollingUpdate",
            },
            "template": {
                "metadata": {"labels": {"deployment": "busybox"}},
                "spec": {
                    "containers": [
                        {
                            "command": ["/bin/sleep", "1000000"],
                            "image": "busybox",
                            "name": "busybox",
                        }
                    ]
                },
            },
        },
    }


@pytest.fixture()
def replicasets(deployment):
    return [
        # last active
        {
            "apiVersion": "apps/v1",
            "kind": "ReplicaSet",
            "metadata": {
                "name": "busybox-current",
                "creationTimestamp": "2022-07-12T09:37:12Z",
                "ownerReferences": [
                    {
                        "apiVersion": "apps/v1",
                        "blockOwnerDeletion": True,
                        "controller": True,
                        "kind": "Deployment",
                        "name": "busybox",
                        "uid": "dab46569-9a6a-43d1-ab6d-53aa410fb737",
                    }
                ],
            },
            "spec": {
                "replicas": 2,
                "selector": {
                    "matchLabels": {
                        "deployment": "busybox",
                        "pod-template-hash": "hashhashhash",
                    }
                },
                "template": deployment["spec"]["template"],
            },
        },
        # older rs
        {
            "apiVersion": "apps/v1",
            "kind": "ReplicaSet",
            "metadata": {
                "name": "busybox-old-one",
                "creationTimestamp": "2022-07-12T09:35:12Z",
                "ownerReferences": [
                    {
                        "apiVersion": "apps/v1",
                        "blockOwnerDeletion": True,
                        "controller": True,
                        "kind": "Deployment",
                        "name": "busybox",
                        "uid": "dab46569-9a6a-43d1-ab6d-53aa410fb737",
                    }
                ],
            },
            "spec": {
                "replicas": 2,
                "selector": {
                    "matchLabels": {
                        "deployment": "busybox",
                        "pod-template-hash": "hashhashhash",
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "deployment": "busybox",
                            "pod-template-hash": "hashhashhash",
                        }
                    },
                    "spec": {
                        "containers": [
                            {
                                "command": ["something different"],
                                "image": "busybox",
                                "name": "busybox",
                            }
                        ],
                    },
                },
            },
        },
        # another RS
        {
            "apiVersion": "apps/v1",
            "kind": "ReplicaSet",
            "metadata": {
                "name": "busybox-older-one",
                "creationTimestamp": "2022-07-12T09:35:12Z",
                "ownerReferences": [
                    {
                        "apiVersion": "apps/v1",
                        "blockOwnerDeletion": True,
                        "controller": True,
                        "kind": "Deployment",
                        "name": "busybox",
                        "uid": "dab46569-9a6a-43d1-ab6d-53aa410fb737",
                    }
                ],
            },
            "spec": {
                "replicas": 2,
                "selector": {
                    "matchLabels": {
                        "deployment": "busybox",
                        "pod-template-hash": "hashhashhash",
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "deployment": "busybox",
                            "pod-template-hash": "hashhashhash",
                        }
                    },
                    "spec": {
                        "containers": [
                            {
                                "command": ["something different whatever"],
                                "image": "busybox",
                                "name": "busybox",
                            }
                        ],
                    },
                },
            },
        },
    ]


def test_get_owned_replicasets(
    mocker,
    oc_cli: OCCli,
    deployment,
):
    oc__get = mocker.patch.object(oc_cli, "get", autospec=True)
    oc__get_obj_root_owner = mocker.patch.object(
        oc_cli, "get_obj_root_owner", autospec=True
    )
    oc__get.return_value = {"items": ["stub1", "stub2", "stub3"]}
    oc__get_obj_root_owner.side_effect = [
        deployment,
        deployment,
        {"kind": "ownerkind", "metadata": {"name": "notownername"}},
    ]
    owned_replicasets = oc_cli.get_owned_replicasets("namespace", deployment)
    assert len(owned_replicasets) == 2


def test_get_replicaset(
    patch_sleep,
    mocker,
    oc_cli: OCCli,
    deployment,
    replicasets,
):
    oc__get_owned_replicasets = mocker.patch.object(
        oc_cli, "get_owned_replicasets", autospec=True
    )
    oc__get_owned_replicasets.return_value = replicasets

    assert (
        oc_cli.get_replicaset("namespace", deployment)["metadata"]["name"]
        == "busybox-current"
    )


def test_get_replicaset_fail(
    patch_sleep,
    mocker,
    oc_cli: OCCli,
    deployment,
):
    oc__get_owned_replicasets = mocker.patch.object(
        oc_cli, "get_owned_replicasets", autospec=True
    )
    oc__get_owned_replicasets.return_value = []

    with pytest.raises(ResourceNotFoundError):
        # pylint: disable-next=expression-not-assigned
        oc_cli.get_replicaset("namespace", deployment)["metadata"]["name"]
    assert oc__get_owned_replicasets.call_count == GET_REPLICASET_MAX_ATTEMPTS


def test_get_replicaset_allow_empty(
    patch_sleep,
    mocker,
    oc_cli: OCCli,
    deployment,
):
    oc__get_owned_replicasets = mocker.patch.object(
        oc_cli, "get_owned_replicasets", autospec=True
    )
    oc__get_owned_replicasets.return_value = []
    assert oc_cli.get_replicaset("namespace", deployment, allow_empty=True) == {}


@pytest.fixture
def api_resources():
    k1_g1 = Resource(
        prefix="", kind="kind1", group="group1", api_version="v1", namespaced=True
    )
    k1_g11 = Resource(
        prefix="", kind="kind1", group="group11", api_version="v1", namespaced=True
    )
    k2_g2 = Resource(
        prefix="", kind="kind2", group="group2", api_version="v2", namespaced=False
    )
    return {"kind1": [k1_g1, k1_g11], "kind2": [k2_g2]}


@pytest.fixture
def oc_api_resources(monkeypatch, mocker, api_resources) -> OCCli:
    monkeypatch.setenv("USE_NATIVE_CLIENT", "False")
    get_api_resources = mocker.patch.object(OCCli, "get_api_resources", autospec=True)
    get_api_resources.return_value = api_resources
    return OC("cluster", "server", "token", local=True, init_api_resources=True)  # type: ignore[return-value]


def test_is_kind_namespaced(oc_api_resources):
    assert oc_api_resources.is_kind_namespaced("kind1")


def test_is_kind_namespaced_full_name(oc_api_resources):
    assert oc_api_resources.is_kind_namespaced("kind1.group11")


def test_is_kind_not_namespaced(oc_api_resources):
    assert not oc_api_resources.is_kind_namespaced("kind2")


def test_is_kind_not_namespaced_full_name(oc_api_resources):
    assert not oc_api_resources.is_kind_namespaced("kind2.group2")


@pytest.fixture
def oc_native(
    monkeypatch,
    mocker,
    api_resources: dict,
) -> OCNative:
    monkeypatch.setenv("USE_NATIVE_CLIENT", "True")
    get_api_resources = mocker.patch.object(OCCli, "get_api_resources", autospec=True)
    get_api_resources.return_value = api_resources
    mocker.patch.object(OCNative, "_get_client", autospec=True)
    return OC("cluster", "server", "token", local=True)  # type: ignore[return-value]


def test_oc_native_get(oc_native: OCNative) -> None:
    oc_native.get("namespace", "kind1", "name")

    oc_native.client.resources.get.assert_called_once_with(
        api_version="group1/v1",
        kind="kind1",
    )
    oc_native.client.resources.get.return_value.get.assert_called_once_with(
        namespace="namespace",
        name="name",
        _request_timeout=60,
    )


def test_oc_native_get_items(oc_native: OCNative) -> None:
    oc_native.get_items("kind1", labels={"label1": "value1"})

    oc_native.client.resources.get.assert_called_once_with(
        api_version="group1/v1",
        kind="kind1",
    )
    oc_native.client.resources.get.return_value.get.assert_called_once_with(
        namespace="",
        label_selector="label1=value1",
        _request_timeout=60,
    )


def test_oc_native_get_items_with_resource_names(oc_native: OCNative) -> None:
    oc_native.get_items("kind1", labels={"label1": "value1"}, resource_names=["name"])

    oc_native.client.resources.get.assert_called_once_with(
        api_version="group1/v1",
        kind="kind1",
    )
    oc_native.client.resources.get.return_value.get.assert_called_once_with(
        namespace="",
        name="name",
        label_selector="label1=value1",
        _request_timeout=60,
    )


def test_oc_native_get_all(oc_native: OCNative) -> None:
    oc_native.get_all("kind1")

    oc_native.client.resources.get.assert_called_once_with(
        api_version="group1/v1",
        kind="kind1",
    )
    oc_native.client.resources.get.return_value.get.assert_called_once_with(
        _request_timeout=60,
    )
