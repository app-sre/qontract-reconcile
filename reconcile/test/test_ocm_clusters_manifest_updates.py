import pytest

from reconcile.ocm.types import (
    OCMClusterNetwork,
    OCMSpec,
    OSDClusterSpec,
)
from reconcile.ocm_clusters import get_app_interface_spec_updates


@pytest.fixture
def cluster_ocm_spec():
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
        domain="0000.p1.openshiftapps.com",
        server_url="https://api.cluster.0000.p1.openshiftapps.com:6443",
        console_url="https://console-openshift-console.apps.cluster.0000.p1.openshiftapps.com",
        elb_fqdn="elb.apps.cluster.0000.p1.openshiftapps.com",
    )
    yield obj


def test_all_attributes_missing(cluster_ocm_spec: OCMSpec):
    current_spec = cluster_ocm_spec
    desired_spec = cluster_ocm_spec.copy(deep=True)
    desired_spec.spec.id = None
    desired_spec.spec.external_id = None
    desired_spec.server_url = ""
    desired_spec.console_url = ""
    desired_spec.elb_fqdn = ""
    updates, _ = get_app_interface_spec_updates("cluster", current_spec, desired_spec)
    assert updates["root"]["consoleUrl"] == current_spec.console_url
    assert updates["root"]["serverUrl"] == current_spec.server_url
    assert updates["root"]["consoleUrl"] == current_spec.console_url
    assert updates["root"]["elbFQDN"] == current_spec.elb_fqdn
    assert updates["spec"]["external_id"] == current_spec.spec.external_id
    assert updates["spec"]["id"] == current_spec.spec.id


def test_all_attributes_changed(cluster_ocm_spec: OCMSpec):
    current_spec = cluster_ocm_spec
    desired_spec = cluster_ocm_spec.copy(deep=True)
    desired_spec.spec.id = "previous-id"
    desired_spec.spec.external_id = "previous-external-id"
    desired_spec.server_url = "previous_server_url"
    desired_spec.console_url = "previous_console_url"
    desired_spec.elb_fqdn = "previous_elb_fqdn"
    updates, _ = get_app_interface_spec_updates("cluster", current_spec, desired_spec)
    assert updates["root"]["consoleUrl"] == current_spec.console_url
    assert updates["root"]["serverUrl"] == current_spec.server_url
    assert updates["root"]["consoleUrl"] == current_spec.console_url
    assert updates["root"]["elbFQDN"] == current_spec.elb_fqdn
    assert updates["spec"]["external_id"] == current_spec.spec.external_id
    assert updates["spec"]["id"] == current_spec.spec.id


def test_elb_fqdn(cluster_ocm_spec: OCMSpec):
    current_spec = cluster_ocm_spec
    desired_spec = cluster_ocm_spec.copy(deep=True)
    desired_spec.elb_fqdn = "non-valid"
    updates, _ = get_app_interface_spec_updates("cluster", current_spec, desired_spec)
    assert updates["root"]["elbFQDN"] == current_spec.console_url.replace(
        "https://console-openshift-console", "elb"
    )
