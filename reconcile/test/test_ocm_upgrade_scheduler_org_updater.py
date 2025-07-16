import json
from collections.abc import Generator, Mapping
from typing import Any

import pytest

from reconcile.ocm.types import OCMClusterNetwork, OCMSpec, OSDClusterSpec
from reconcile.ocm_upgrade_scheduler_org_updater import render_policy
from reconcile.utils.jinja2.utils import Jinja2TemplateError


@pytest.fixture
def cluster_ocm_spec() -> Generator[OCMSpec, None, None]:
    n = OCMClusterNetwork(
        vpc="10.112.0.0/16",
        service="10.120.0.0/16",
        pod="10.128.0.0/14",
        type=None,
    )
    spec = OSDClusterSpec(
        product="osd",
        channel="stable",
        instance_type="m5.xlarge",
        multi_az=False,
        private=False,
        region="us-east-1",
        version="4.10.0",
        load_balancers=5,
        storage=1100,
        provider="aws",
        id="cluster-id",
        external_id="external-id",
        hypershift=False,
        disable_user_workload_monitoring=False,
        autoscale=None,
        nodes=None,
        provision_shard_id=None,
        initial_version=None,
    )
    obj = OCMSpec(
        spec=spec,
        network=n,
        path=None,
        domain=None,
        serverUrl="server-url",
        consoleUrl="console-url",
        elbFQDN="elb-fqdn",
    )
    yield obj


@pytest.fixture
def labels() -> dict[str, str]:
    return {"key1": "value1", "key2": "value2"}


@pytest.fixture
def variables() -> str:
    return json.dumps({"var1": "value1", "var2": "value2"})


def create_template_info(
    content: str, type: str = "jinja2", variables: str | None = None
) -> dict[str, Any]:
    return {
        "path": {
            "content": content,
        },
        "type": type,
        "variables": variables,
    }


def test_render_policy_basic(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str]
) -> None:
    template_info = create_template_info("hello: world")
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": "world"}


def test_render_policy_cluster_spec(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str]
) -> None:
    template_info = create_template_info("hello: {{ cluster.spec.region }}")
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": cluster_ocm_spec.spec.region}


def test_render_policy_cluster_spec_bad_attribute(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str]
) -> None:
    template_info = create_template_info("hello: {{ cluster.unkown_attribute }}")
    with pytest.raises(Jinja2TemplateError):
        render_policy(template_info, cluster_ocm_spec, labels, settings={})


def test_render_policy_cluster_labels(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str]
) -> None:
    template_info = create_template_info("hello: {{ labels.key1 }}")
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": labels["key1"]}

    template_info = create_template_info("hello: {{ labels['key1'] }}")
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": labels["key1"]}


def test_render_policy_cluster_labels_missing(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str]
) -> None:
    template_info = create_template_info("hello: {{ labels.unknown_key }}")
    with pytest.raises(Jinja2TemplateError):
        render_policy(template_info, cluster_ocm_spec, labels, settings={})

    template_info = create_template_info("hello: {{ labels['unknown_key'] }}")
    with pytest.raises(Jinja2TemplateError):
        render_policy(template_info, cluster_ocm_spec, labels, settings={})


def test_render_policy_cluster_labels_default(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str]
) -> None:
    template_info = create_template_info(
        "hello: {{ labels.unknown_key | default('OK') }}"
    )
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": "OK"}

    template_info = create_template_info(
        "hello: {{ labels['unknown_key'] | default('OK') }}"
    )
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": "OK"}


def test_render_policy_variables(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str], variables: str
) -> None:
    template_info = create_template_info("hello: {{ var1 }}", variables=variables)
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": "value1"}


def test_render_policy_variables_missing(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str], variables: str
) -> None:
    template_info = create_template_info("hello: {{ unkown_var }}", variables=variables)
    with pytest.raises(Jinja2TemplateError):
        render_policy(template_info, cluster_ocm_spec, labels, settings={})


def test_render_policy_variables_default(
    cluster_ocm_spec: OCMSpec, labels: Mapping[str, str], variables: str
) -> None:
    template_info = create_template_info(
        "hello: {{ unkown_var | default('OK') }}", variables=variables
    )
    rendered = render_policy(template_info, cluster_ocm_spec, labels, settings={})
    assert rendered == {"hello": "OK"}
