from pydantic import ValidationError
import pytest

from reconcile.ocm.types import (
    OCMClusterNetwork,
    OCMSpec,
    OSDClusterSpec,
    ROSAClusterSpec,
)
from unittest.mock import patch
from reconcile.utils.ocm import SPEC_ATTR_CONSOLE_URL, SPEC_ATTR_SERVER_URL, OCMMap, OCM
from reconcile import mr_client_gateway
from reconcile.utils.mr.clusters_updates import CreateClustersUpdates
from reconcile import queries
import reconcile.ocm_clusters as occ
import reconcile.utils.ocm as ocmmod
import typing

from .fixtures import Fixtures


fxt = Fixtures("clusters")


@pytest.fixture
def ocm_osd_cluster_raw_spec():
    return fxt.get_anymarkup("osd_spec.json")


@pytest.fixture
def ocm_osd_cluster_ai_spec():
    return fxt.get_anymarkup("osd_spec_ai.yml")


@pytest.fixture
def ocm_rosa_cluster_raw_spec():
    return fxt.get_anymarkup("rosa_spec.json")


@pytest.fixture
def ocm_osd_cluster_spec():
    n = OCMClusterNetwork(
        type="OpenShiftSDN",
        vpc="10.112.0.0/16",
        service="10.120.0.0/16",
        pod="10.128.0.0/14",
    )
    spec = OSDClusterSpec(
        product="osd",
        autoscale=None,
        channel="stable",
        disable_user_workload_monitoring=True,
        external_id="the-cluster-external_id",
        id="the-cluster-id",
        instance_type="m5.xlarge",
        multi_az=False,
        nodes=5,
        private=False,
        provision_shard_id="the-cluster-provision_shard_id",
        region="us-east-1",
        version="4.10.0",
        load_balancers=5,
        storage=1100,
        provider="aws",
    )
    obj = OCMSpec(
        spec=spec,
        network=n,
        domain="devshift.net",
        server_url="the-cluster-server_url",
        console_url="the-cluster-console_url",
    )
    yield obj


@pytest.fixture
def osd_cluster_fxt():
    return {
        "spec": {
            "product": "osd",
            "storage": 1100,
            "load_balancers": 5,
            "id": "the-cluster-id",
            "external_id": "the-cluster-external_id",
            "provider": "aws",
            "region": "us-east-1",
            "channel": "stable",
            "version": "4.10.0",
            "initial_version": "4.9.0-candidate",
            "multi_az": False,
            "nodes": 5,
            "instance_type": "m5.xlarge",
            "private": False,
            "provision_shard_id": "the-cluster-provision_shard_id",
            "disable_user_workload_monitoring": True,
        },
        "network": {
            "type": None,
            "vpc": "10.112.0.0/16",
            "service": "10.120.0.0/16",
            "pod": "10.128.0.0/14",
        },
        "ocm": {
            "name": "non-existent-ocm",
            "url": "https://api.non-existent-ocm.com",
            "accessTokenClientId": "cloud-services",
            "accessTokenUrl": "https://sso.blah.com/token",
            "offlineToken": {
                "path": "a-secret-path",
                "field": "offline_token",
                "format": None,
                "version": None,
            },
            "blockedVersions": ["^.*-fc\\..*$"],
        },
        "consoleUrl": "the-cluster-console_url",
        "serverUrl": "the-cluster-server_url",
        "elbFQDN": "the-cluster-elbFQDN",
        "path": "the-cluster-path",
        "name": "cluster1",
        "id": "anid",
        "managed": True,
        "state": "ready",
    }


@pytest.fixture
def rosa_cluster_fxt():
    return {
        "spec": {
            "product": "rosa",
            "id": "the-cluster-id",
            "external_id": "the-cluster-external_id",
            "provider": "aws",
            "region": "us-east-1",
            "channel": "stable",
            "version": "4.10.0",
            "initial_version": "4.9.0-candidate",
            "multi_az": False,
            "nodes": 5,
            "instance_type": "m5.xlarge",
            "private": False,
            "provision_shard_id": "the-cluster-provision_shard_id",
            "disable_user_workload_monitoring": True,
        },
        "network": {
            "type": None,
            "vpc": "10.112.0.0/16",
            "service": "10.120.0.0/16",
            "pod": "10.128.0.0/14",
        },
        "ocm": {
            "name": "non-existent-ocm",
            "url": "https://api.non-existent-ocm.com",
            "accessTokenClientId": "cloud-services",
            "accessTokenUrl": "https://sso.blah.com/token",
            "offlineToken": {
                "path": "a-secret-path",
                "field": "offline_token",
                "format": None,
                "version": None,
            },
            "blockedVersions": ["^.*-fc\\..*$"],
        },
        "consoleUrl": "the-cluster-console_url",
        "serverUrl": "the-cluster-server_url",
        "elbFQDN": "the-cluster-elbFQDN",
        "path": "the-cluster-path",
        "name": "cluster1",
        "id": "anid",
        "managed": True,
        "state": "ready",
    }


@pytest.fixture
def queries_mock(osd_cluster_fxt):
    with patch.object(queries, "get_app_interface_settings", autospec=True) as s:
        with patch.object(queries, "get_clusters", autospec=True) as gc:
            s.return_value = {}
            gc.return_value = [osd_cluster_fxt]
            yield s, gc


@pytest.fixture
def ocmmap_mock(ocm_osd_cluster_spec, ocm_mock):
    with patch.object(OCMMap, "get", autospec=True) as get:
        with patch.object(OCMMap, "init_ocm_client", autospec=True):
            with patch.object(OCMMap, "cluster_specs", autospec=True) as cs:
                get.return_value = ocm_mock
                cs.return_value = ({"cluster1": ocm_osd_cluster_spec}, {})
                yield get, cs


@pytest.fixture
def ocm_secrets_reader():
    with patch("reconcile.utils.ocm.SecretReader", autospec=True) as sr:
        yield sr


@pytest.fixture
def ocm_mock(ocm_secrets_reader):
    with patch.object(OCM, "_post", autospec=True) as _post:
        with patch.object(OCM, "_patch", autospec=True) as _patch:
            with patch.object(OCM, "_init_access_token", autospec=True):
                with patch.object(OCM, "get_provision_shard", autospec=True) as gps:
                    gps.return_value = {"id": "provision_shard_id"}
                    yield _post, _patch


@pytest.fixture
def cluster_updates_mr_mock():
    with patch.object(mr_client_gateway, "init", autospec=True):
        with patch.object(CreateClustersUpdates, "submit", autospec=True) as ccu:
            yield ccu


@pytest.fixture
def get_json_mock():
    with patch.object(OCM, "_get_json", autospec=True) as get_json:
        yield get_json


def test_ocm_spec_population_rosa(rosa_cluster_fxt):
    n = OCMSpec(**rosa_cluster_fxt)
    assert isinstance(n.spec, ROSAClusterSpec)


def test_ocm_spec_population_osd(osd_cluster_fxt):
    n = OCMSpec(**osd_cluster_fxt)
    assert isinstance(n.spec, OSDClusterSpec)
    assert n.server_url == osd_cluster_fxt[SPEC_ATTR_SERVER_URL]
    assert n.console_url == osd_cluster_fxt[SPEC_ATTR_CONSOLE_URL]


def test_ocm_spec_population_osd_with_extra(osd_cluster_fxt):
    osd_cluster_fxt["spec"]["extra_attribute"] = True
    with pytest.raises(ValidationError):
        OCMSpec(**osd_cluster_fxt)


def test_get_ocm_cluster_update_spec_no_changes(
    ocm_mock, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = ocm_osd_cluster_spec
    upd, err = occ.get_cluster_ocm_update_spec(
        ocm_mock, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == ({}, False)


def test_get_ocm_cluster_update_spec_network_banned(
    ocm_mock, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.network.vpc = "0.0.0.0/0"
    _, err = occ.get_cluster_ocm_update_spec(
        ocm_mock, "cluster1", current_spec, desired_spec
    )
    assert err is True


@typing.no_type_check
def test_get_ocm_cluster_update_spec_allowed_change(
    ocm_mock, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.spec.storage = 2000
    upd, err = occ.get_cluster_ocm_update_spec(
        ocm_mock, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == ({ocmmod.SPEC_ATTR_STORAGE: 2000}, False)


def test_get_ocm_cluster_update_spec_not_allowed_change(
    ocm_mock, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.spec.multi_az = not desired_spec.spec.multi_az
    upd, err = occ.get_cluster_ocm_update_spec(
        ocm_mock, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == (
        {ocmmod.SPEC_ATTR_MULTI_AZ: desired_spec.spec.multi_az},
        True,
    )


def test_get_ocm_cluster_update_spec_disable_uwm(
    ocm_mock, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.spec.disable_user_workload_monitoring = (
        not desired_spec.spec.disable_user_workload_monitoring
    )
    upd, err = occ.get_cluster_ocm_update_spec(
        ocm_mock, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == (
        {
            ocmmod.SPEC_ATTR_DISABLE_UWM: desired_spec.spec.disable_user_workload_monitoring
        },
        False,
    )


def test_noop_dry_run(queries_mock, ocmmap_mock, ocm_mock, cluster_updates_mr_mock):
    with pytest.raises(SystemExit):
        occ.run(False)
    # If get has not been called means no action has been performed
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_changed_id(
    get_json_mock,
    queries_mock,
    ocm_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
    cluster_updates_mr_mock,
):
    # App Interface attributes are only considered if are null or blank
    # Won't be better to update them if have changed?
    ocm_osd_cluster_ai_spec["spec"]["id"] = ""
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]
    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}

    with pytest.raises(SystemExit):
        occ.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 1


def test_ocm_osd_create_cluster(
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
):
    ocm_osd_cluster_ai_spec["name"] = "a-new-cluster"
    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]
    with pytest.raises(SystemExit):
        occ.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 1
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_ocm_osd_update_cluster(
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
):
    ocm_osd_cluster_ai_spec["spec"]["storage"] = 40000
    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]
    with pytest.raises(SystemExit):
        occ.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 1
    assert cluster_updates_mr_mock.call_count == 0


def test_ocm_returns_a_rosa_cluster(
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_osd_cluster_raw_spec,
    ocm_rosa_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
):
    get_json_mock.return_value = {
        "items": [ocm_osd_cluster_raw_spec, ocm_rosa_cluster_raw_spec]
    }
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]
    with pytest.raises(SystemExit):
        occ.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_ocm_create_rosa_cluster_should_not_post_anything(
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_osd_cluster_ai_spec,
):
    get_json_mock.return_value = {"items": []}
    ocm_osd_cluster_ai_spec["spec"]["product"] = "rosa"
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]
    with pytest.raises(SystemExit):
        occ.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_changed_ocm_spec_disable_uwm(
    get_json_mock,
    queries_mock,
    ocm_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
    cluster_updates_mr_mock,
):

    ocm_osd_cluster_ai_spec["spec"][
        "disable_user_workload_monitoring"
    ] = not ocm_osd_cluster_ai_spec["spec"]["disable_user_workload_monitoring"]

    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]

    with pytest.raises(SystemExit):
        occ.run(dry_run=False)

    _post, _patch = ocm_mock
    assert _patch.call_count == 1
    assert _post.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_missing_ocm_spec_disable_uwm(
    get_json_mock,
    queries_mock,
    ocm_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
    cluster_updates_mr_mock,
):
    ocm_osd_cluster_ai_spec["spec"]["disable_user_workload_monitoring"] = None

    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]

    with pytest.raises(SystemExit):
        occ.run(dry_run=False)
    _post, _patch = ocm_mock

    assert _patch.call_count == 1
    assert _post.call_count == 0
    assert cluster_updates_mr_mock.call_count == 1
