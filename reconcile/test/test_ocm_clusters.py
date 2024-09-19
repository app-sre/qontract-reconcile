# ruff: noqa: SIM117
import typing
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from pytest_mock import MockerFixture

import reconcile.ocm_clusters as occ
import reconcile.utils.ocm as ocmmod
from reconcile import (
    mr_client_gateway,
    queries,
)
from reconcile.ocm.types import (
    ClusterMachinePool,
    OCMClusterNetwork,
    OCMSpec,
    OSDClusterSpec,
    ROSAClusterSpec,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils.mr.clusters_updates import CreateClustersUpdates
from reconcile.utils.ocm import (
    OCM,
    SPEC_ATTR_CONSOLE_URL,
    SPEC_ATTR_SERVER_URL,
    OCMMap,
    ocm,
    products,
)
from reconcile.utils.ocm.products import (
    OCM_PRODUCT_OSD,
    OCM_PRODUCT_ROSA,
    OCMProductOsd,
    OCMProductPortfolio,
    OCMProductRosa,
)
from reconcile.utils.ocm_base_client import OCMBaseClient

fxt = Fixtures("clusters")


@pytest.fixture
def ocm_osd_cluster_raw_spec():
    return fxt.get_anymarkup("osd_spec.json")


@pytest.fixture
def ocm_osd_cluster_ai_spec():
    return fxt.get_anymarkup("osd_spec_ai.yml")


@pytest.fixture
def ocm_osd_cluster_post_spec():
    return fxt.get_anymarkup("osd_spec_post.json")


@pytest.fixture
def ocm_rosa_cluster_raw_spec():
    return fxt.get_anymarkup("rosa_spec.json")


@pytest.fixture
def ocm_rosa_cluster_ai_spec():
    return fxt.get_anymarkup("rosa_spec_ai.yml")


@pytest.fixture
def ocm_rosa_cluster_post_spec():
    return fxt.get_anymarkup("rosa_spec_post.json")


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
        channel="stable",
        disable_user_workload_monitoring=True,
        external_id="the-cluster-external_id",
        id="the-cluster-id",
        multi_az=False,
        private=False,
        provision_shard_id="the-cluster-provision_shard_id",
        region="us-east-1",
        version="4.10.0",
        load_balancers=5,
        storage=1100,
        provider="aws",
    )
    machine_pools = [
        ClusterMachinePool(
            id="worker",
            instance_type="m5.xlarge",
            replicas=5,
        )
    ]
    obj = OCMSpec(
        spec=spec,
        machine_pools=machine_pools,
        network=n,
        domain="devshift.net",
        server_url="https://api.test-cluster.0000.p1.openshiftapps.com:6443",
        console_url="https://console-openshift-console.test-cluster.0000.p1.openshiftapps.com",
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
            "private": False,
            "provision_shard_id": "the-cluster-provision_shard_id",
            "disable_user_workload_monitoring": True,
        },
        "machinePools": [
            {
                "id": "worker",
                "instance_type": "m5.xlarge",
                "replicas": 5,
            }
        ],
        "network": {
            "type": None,
            "vpc": "10.112.0.0/16",
            "service": "10.120.0.0/16",
            "pod": "10.128.0.0/14",
        },
        "ocm": {
            "name": "non-existent-ocm",
            "environment": {
                "name": "name",
                "url": "https://api.non-existent-ocm.com",
                "accessTokenClientId": "cloud-services",
                "accessTokenUrl": "https://sso.blah.com/token",
                "accessTokenClientSecret": {
                    "path": "a-secret-path",
                    "field": "client_secret",
                    "format": None,
                    "version": None,
                },
            },
            "orgId": "org_id",
            "accessTokenClientId": "cloud-services",
            "accessTokenUrl": "https://sso.blah.com/token",
            "accessTokenClientSecret": {
                "path": "a-secret-path",
                "field": "client_secret",
                "format": None,
                "version": None,
            },
            "blockedVersions": ["^.*-fc\\..*$"],
        },
        "consoleUrl": "https://console-openshift-console.test-cluster.0000.p1.openshiftapps.com",
        "serverUrl": "https://api.test-cluster.0000.p1.openshiftapps.com:6443",
        "elbFQDN": "elb.test-cluster.0000.p1.openshiftapps.com",
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
            "account": {
                "uid": "123123123",
                "rosa": {
                    "creator_role_arn": "creator_role",
                    "sts": {
                        "installer_role_arn": "installer_role",
                        "support_role_arn": " support_role",
                        "controlplane_role_arn": "controlplane_role",
                        "worker_role_arn": "worker_role",
                    },
                },
            },
            "id": "the-cluster-id",
            "external_id": "the-cluster-external_id",
            "provider": "aws",
            "region": "us-east-1",
            "channel": "stable",
            "version": "4.10.0",
            "initial_version": "4.9.0-candidate",
            "multi_az": False,
            "private": False,
            "provision_shard_id": "the-cluster-provision_shard_id",
            "disable_user_workload_monitoring": True,
        },
        "machinePools": [
            {
                "id": "worker",
                "instance_type": "m5.xlarge",
                "replicas": 5,
            },
        ],
        "network": {
            "type": None,
            "vpc": "10.112.0.0/16",
            "service": "10.120.0.0/16",
            "pod": "10.128.0.0/14",
        },
        "ocm": {
            "name": "non-existent-ocm",
            "environment": {
                "name": "name",
                "url": "https://api.non-existent-ocm.com",
                "accessTokenClientId": "cloud-services",
                "accessTokenUrl": "https://sso.blah.com/token",
                "accessTokenClientSecret": {
                    "path": "a-secret-path",
                    "field": "client_secret",
                    "format": None,
                    "version": None,
                },
            },
            "orgId": "org_id",
            "accessTokenClientId": "cloud-services",
            "accessTokenUrl": "https://sso.blah.com/token",
            "accessTokenClientSecret": {
                "path": "a-secret-path",
                "field": "client_secret",
                "format": None,
                "version": None,
            },
            "blockedVersions": ["^.*-fc\\..*$"],
        },
        "consoleUrl": "https://console-openshift-console.0000.p1.openshiftapps.com",
        "serverUrl": "https://api.tst-jpr-rosa.0000.p1.openshiftapps.com:6443",
        "elbFQDN": "elb.tst-jpr-rosa.0000.p1.openshiftapps.com",
        "path": "the-cluster-path",
        "name": "cluster1",
        "id": "anid",
        "managed": True,
        "state": "ready",
    }


@pytest.fixture
def rosa_hosted_cp_cluster_fxt():
    return {
        "spec": {
            "product": "rosa",
            "account": {
                "uid": "123123123",
                "rosa": {
                    "creator_role_arn": "creator_role",
                    "sts": {
                        "installer_role_arn": "installer_role",
                        "support_role_arn": " support_role",
                        "worker_role_arn": "worker_role",
                    },
                },
            },
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
            "hypershift": True,
        },
        "network": {
            "type": None,
            "vpc": "10.112.0.0/16",
            "service": "10.120.0.0/16",
            "pod": "10.128.0.0/14",
        },
        "ocm": {
            "name": "non-existent-ocm",
            "orgId": "org_id",
            "environment": {
                "name": "name",
                "url": "https://api.non-existent-ocm.com",
                "accessTokenClientId": "cloud-services",
                "accessTokenUrl": "https://sso.blah.com/token",
                "accessTokenClientSecret": {
                    "path": "a-secret-path",
                    "field": "offline_token",
                    "format": None,
                    "version": None,
                },
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
        with patch.object(OCMMap, "init_ocm_client_from_cluster", autospec=True):
            with patch.object(OCMMap, "cluster_specs", autospec=True) as cs:
                get.return_value = ocm_mock
                cs.return_value = ({"cluster1": ocm_osd_cluster_spec}, {})
                yield get, cs


@pytest.fixture
def ocm_mock(mocker: MockerFixture):
    with patch.object(OCM, "whoami", autospec=True):
        with patch.object(ocm, "init_ocm_base_client") as ioc:
            ocm_api_mock = mocker.Mock(OCMBaseClient)
            ioc.return_value = ocm_api_mock
            yield ocm_api_mock.post, ocm_api_mock.patch
            # todo check if we need this realy!!!
            # with patch.object(OCM, "get_product_impl", autospec=True) as gpi:
            #    gpi.return_value = osd_product
            #    yield _post, _patch


@pytest.fixture
def cluster_updates_mr_mock():
    with patch.object(mr_client_gateway, "init", autospec=True):
        with patch.object(CreateClustersUpdates, "submit", autospec=True) as ccu:
            yield ccu


@pytest.fixture
def get_json_mock():
    with patch.object(OCM, "_get_json", autospec=True) as get_json:
        yield get_json


@pytest.fixture
def osd_product() -> typing.Generator[OCMProductOsd, None, None]:
    with patch.object(products, "get_provisioning_shard_id") as g:
        g.return_value = "provision_shard_id"
        yield OCMProductOsd()


@pytest.fixture
def rosa_product() -> typing.Generator[OCMProductRosa, None, None]:
    with patch.object(products, "get_provisioning_shard_id") as g:
        g.return_value = "provision_shard_id"
        yield OCMProductRosa(None)


@pytest.fixture
def product_portfolio(
    osd_product: OCMProductOsd, rosa_product: OCMProductRosa
) -> OCMProductPortfolio:
    return OCMProductPortfolio(
        products={
            OCM_PRODUCT_OSD: osd_product,
            OCM_PRODUCT_ROSA: rosa_product,
        }
    )


@pytest.fixture
def integration(
    product_portfolio: OCMProductPortfolio,
) -> typing.Generator[occ.OcmClusters, None, None]:
    integration = occ.OcmClusters(
        params=occ.OcmClustersParams(
            job_controller_cluster="cluster",
            job_controller_namespace="namespace",
            rosa_job_image="image",
            rosa_job_service_account="service_account",
            rosa_role="role",
            gitlab_project_id=None,
            thread_pool_size=1,
        )
    )
    with patch.object(
        integration, "assemble_product_portfolio", return_value=product_portfolio
    ):
        yield integration


def test_ocm_spec_population_rosa(rosa_cluster_fxt):
    n = OCMSpec(**rosa_cluster_fxt)
    assert isinstance(n.spec, ROSAClusterSpec)


def test_ocm_spec_population_hcp(rosa_hosted_cp_cluster_fxt):
    n = OCMSpec(**rosa_hosted_cp_cluster_fxt)
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
    osd_product: OCMProductOsd, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = ocm_osd_cluster_spec
    upd, err = occ.get_cluster_ocm_update_spec(
        osd_product, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == ({}, False)


def test_get_ocm_cluster_update_spec_network_banned(
    osd_product: OCMProductOsd, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.network.vpc = "0.0.0.0/0"
    _, err = occ.get_cluster_ocm_update_spec(
        osd_product, "cluster1", current_spec, desired_spec
    )
    assert err is True


def test_get_ocm_cluster_update_spec_network_type_ignored(
    osd_product: OCMProductOsd, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.network.type = "OVNKubernetes"
    upd, err = occ.get_cluster_ocm_update_spec(
        osd_product, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == ({}, False)


@typing.no_type_check
def test_get_ocm_cluster_update_spec_allowed_change(
    osd_product: OCMProductOsd, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.spec.storage = 2000
    upd, err = occ.get_cluster_ocm_update_spec(
        osd_product, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == ({ocmmod.SPEC_ATTR_STORAGE: 2000}, False)


def test_get_ocm_cluster_update_spec_not_allowed_change(
    osd_product: OCMProductOsd, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.spec.multi_az = not desired_spec.spec.multi_az
    upd, err = occ.get_cluster_ocm_update_spec(
        osd_product, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == (
        {ocmmod.SPEC_ATTR_MULTI_AZ: desired_spec.spec.multi_az},
        True,
    )


def test_get_ocm_cluster_update_spec_disable_uwm(
    osd_product: OCMProductOsd, ocm_osd_cluster_spec: OCMSpec
):
    current_spec = ocm_osd_cluster_spec
    desired_spec = current_spec.copy(deep=True)
    desired_spec.spec.disable_user_workload_monitoring = (
        not desired_spec.spec.disable_user_workload_monitoring
    )
    upd, err = occ.get_cluster_ocm_update_spec(
        osd_product, "cluster1", current_spec, desired_spec
    )
    assert (upd, err) == (
        {
            ocmmod.SPEC_ATTR_DISABLE_UWM: desired_spec.spec.disable_user_workload_monitoring
        },
        False,
    )


def test_noop_dry_run(
    integration: occ.OcmClusters,
    queries_mock,
    ocmmap_mock,
    ocm_mock,
    cluster_updates_mr_mock,
) -> None:
    with pytest.raises(SystemExit):
        integration.run(False)
    # If get has not been called means no action has been performed
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_changed_id(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
    cluster_updates_mr_mock,
) -> None:
    # App Interface attributes are only considered if are null or blank
    # Won't be better to update them if have changed?
    ocm_osd_cluster_ai_spec["spec"]["id"] = ""
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]
    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}

    with pytest.raises(SystemExit):
        integration.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 1


def test_ocm_osd_create_cluster(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_osd_cluster_ai_spec,
    ocm_osd_cluster_post_spec,
):
    get_json_mock.return_value = {"items": []}
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]

    with pytest.raises(SystemExit) as sys_exit:
        integration.run(dry_run=False)

    assert sys_exit.value.code == 0
    _post, _patch = ocm_mock
    _post.assert_called_once_with(
        "/api/clusters_mgmt/v1/clusters",
        ocm_osd_cluster_post_spec,
        {},
    )
    _patch.assert_not_called()
    cluster_updates_mr_mock.assert_not_called()


def test_ocm_osd_create_cluster_without_machine_pools(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_osd_cluster_ai_spec,
    ocm_osd_cluster_post_spec,
):
    get_json_mock.return_value = {"items": []}
    bad_spec = ocm_osd_cluster_ai_spec | {"machinePools": []}
    queries_mock[1].return_value = [bad_spec]

    with pytest.raises(SystemExit) as sys_exit:
        integration.run(dry_run=False)

    assert sys_exit.value.code == 1
    _post, _patch = ocm_mock
    _post.assert_not_called()
    _patch.assert_not_called()
    cluster_updates_mr_mock.assert_not_called()


def test_ocm_rosa_update_cluster(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_rosa_cluster_raw_spec,
    ocm_rosa_cluster_ai_spec,
):
    ocm_rosa_cluster_ai_spec["spec"]["channel"] = "rapid"
    get_json_mock.return_value = {"items": [ocm_rosa_cluster_raw_spec]}
    queries_mock[1].return_value = [ocm_rosa_cluster_ai_spec]
    with pytest.raises(SystemExit):
        integration.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 1
    assert cluster_updates_mr_mock.call_count == 0


def test_ocm_rosa_update_cluster_dont_update_ocm_on_oidc_drift(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_rosa_cluster_raw_spec,
    ocm_rosa_cluster_ai_spec,
):
    ocm_rosa_cluster_ai_spec["spec"]["oidc_endpoint_url"] = "some-other-oidc-url"
    get_json_mock.return_value = {"items": [ocm_rosa_cluster_raw_spec]}
    queries_mock[1].return_value = [ocm_rosa_cluster_ai_spec]
    with pytest.raises(SystemExit):
        integration.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 1


def test_ocm_rosa_update_cluster_with_machine_pools_change(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_rosa_cluster_raw_spec,
    ocm_rosa_cluster_ai_spec,
):
    new_spec = ocm_rosa_cluster_ai_spec | {
        "machinePools": [
            {
                "id": "new",
                "instance_type": "m5.xlarge",
                "replicas": 1,
            }
        ]
    }
    get_json_mock.return_value = {"items": [ocm_rosa_cluster_raw_spec]}
    queries_mock[1].return_value = [new_spec]

    with pytest.raises(SystemExit):
        integration.run(dry_run=False)

    _post, _patch = ocm_mock
    _post.assert_not_called()
    _patch.assert_not_called()
    cluster_updates_mr_mock.assert_not_called()


def test_ocm_osd_update_cluster(
    integration: occ.OcmClusters,
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
        integration.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 1
    assert cluster_updates_mr_mock.call_count == 0


def test_ocm_osd_update_cluster_with_machine_pools_change(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    cluster_updates_mr_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
):
    new_spec = ocm_osd_cluster_ai_spec | {
        "machinePools": [
            {
                "id": "new",
                "instance_type": "m5.xlarge",
                "replicas": 1,
            }
        ]
    }
    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}
    queries_mock[1].return_value = [new_spec]

    with pytest.raises(SystemExit):
        integration.run(dry_run=False)

    _post, _patch = ocm_mock
    _post.assert_not_called()
    _patch.assert_not_called()
    cluster_updates_mr_mock.assert_not_called()


def test_ocm_returns_a_rosa_cluster(
    integration: occ.OcmClusters,
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
        integration.run(dry_run=False)
    _post, _patch = ocm_mock
    assert _post.call_count == 0
    assert _patch.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_changed_ocm_spec_disable_uwm(
    integration: occ.OcmClusters,
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
        integration.run(dry_run=False)

    _post, _patch = ocm_mock
    assert _patch.call_count == 1
    assert _post.call_count == 0
    assert cluster_updates_mr_mock.call_count == 0


def test_console_url_changes_ai(
    integration: occ.OcmClusters,
    get_json_mock,
    queries_mock,
    ocm_mock,
    ocm_osd_cluster_raw_spec,
    ocm_osd_cluster_ai_spec,
    cluster_updates_mr_mock,
):
    ocm_osd_cluster_ai_spec["consoleUrl"] = "old-console-url"

    get_json_mock.return_value = {"items": [ocm_osd_cluster_raw_spec]}
    queries_mock[1].return_value = [ocm_osd_cluster_ai_spec]

    with pytest.raises(SystemExit):
        integration.run(dry_run=False)

    _post, _patch = ocm_mock
    assert _patch.call_count == 0
    assert _post.call_count == 0
    assert cluster_updates_mr_mock.call_count == 1
