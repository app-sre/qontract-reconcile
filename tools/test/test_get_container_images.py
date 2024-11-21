import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.namespaces_minimal import ClusterV1, NamespaceV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import OCNative
from reconcile.utils.oc_map import OCMap
from tools.cli_commands.container_images_report import (
    fetch_pods_images_from_namespaces,
)

fxt = Fixtures("container_images_report")


@pytest.fixture
def observability_pods() -> list[dict]:
    return fxt.get_anymarkup("app-sre-observability-stage-pods.yaml")


@pytest.fixture
def pipeline_pods() -> list[dict]:
    return fxt.get_anymarkup("app-sre-pipelines-pods.yaml")


@pytest.fixture
def namespaces() -> list[NamespaceV1]:
    return [
        NamespaceV1(
            name="app-sre-observability-stage",
            delete=None,
            labels="{}",
            clusterAdmin=None,
            cluster=ClusterV1(
                name="appsres09ue1",
                serverUrl="https://api.appsres09ue1.24ep.p3.openshiftapps.com:443",
                insecureSkipTLSVerify=None,
                jumpHost=None,
                automationToken=VaultSecret(
                    path="app-sre/integrations-output/openshift-cluster-bots/appsres09ue1",
                    field="token",
                    version=None,
                    format=None,
                ),
                clusterAdminAutomationToken=VaultSecret(
                    path="app-sre/integrations-output/openshift-cluster-bots/appsres09ue1-cluster-admin",
                    field="token",
                    version=None,
                    format=None,
                ),
                internal=True,
                disable=None,
            ),
        ),
        NamespaceV1(
            name="app-sre-pipelines",
            delete=None,
            labels='{"provider": "tekton"}',
            clusterAdmin=None,
            cluster=ClusterV1(
                name="appsres09ue1",
                serverUrl="https://api.appsres09ue1.24ep.p3.openshiftapps.com:443",
                insecureSkipTLSVerify=None,
                jumpHost=None,
                automationToken=VaultSecret(
                    path="app-sre/integrations-output/openshift-cluster-bots/appsres09ue1",
                    field="token",
                    version=None,
                    format=None,
                ),
                clusterAdminAutomationToken=VaultSecret(
                    path="app-sre/integrations-output/openshift-cluster-bots/appsres09ue1-cluster-admin",
                    field="token",
                    version=None,
                    format=None,
                ),
                internal=True,
                disable=None,
            ),
        ),
    ]


@pytest.fixture
def oc(
    mocker: MockerFixture,
    observability_pods: list[dict],
    pipeline_pods: list[dict],
) -> OCNative:
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get_items.side_effect = [observability_pods, pipeline_pods]
    return oc


@pytest.fixture
def oc_map(mocker: MockerFixture, oc: OCNative) -> OCMap:
    oc_map = mocker.patch("reconcile.utils.oc_map.OCMap", autospec=True)
    oc_map.get_cluster.return_value = oc
    return oc_map


# convert a list of dicts into a set of tuples to use it in assertions
def _to_set(list_of_dicts: list[dict]) -> set[tuple]:
    return {tuple(d.items()) for d in list_of_dicts}


def testfetch_no_filter(namespaces: list[NamespaceV1], oc_map: OCMap) -> None:
    images = fetch_pods_images_from_namespaces(
        namespaces=namespaces,
        oc_map=oc_map,
        thread_pool_size=2,
    )

    assert _to_set(images) == _to_set([
        {
            "name": "quay.io/prometheus/blackbox-exporter",
            "namespaces": "app-sre-observability-stage",
            "count": 1,
        },
        {
            "name": "quay.io/redhat-services-prod/app-sre-tenant/gitlab-project-exporter-main/gitlab-project-exporter-main",
            "namespaces": "app-sre-observability-stage",
            "count": 1,
        },
        {
            "name": "quay.io/app-sre/internal-redhat-ca",
            "namespaces": "app-sre-observability-stage,app-sre-pipelines",
            "count": 3,
        },
        {
            "name": "quay.io/app-sre/clamav",
            "namespaces": "app-sre-pipelines",
            "count": 1,
        },
        {
            "name": "quay.io/redhat-appstudio/clamav-db",
            "namespaces": "app-sre-pipelines",
            "count": 1,
        },
        {
            "name": "registry.redhat.io/openshift-pipelines/pipelines-entrypoint-rhel8",
            "namespaces": "app-sre-pipelines",
            "count": 3,
        },
        {
            "name": "quay.io/redhatproductsecurity/rapidast",
            "namespaces": "app-sre-pipelines",
            "count": 1,
        },
    ])


def testfetch_exclude_pattern(namespaces: list[NamespaceV1], oc_map: OCMap) -> None:
    images = fetch_pods_images_from_namespaces(
        namespaces=namespaces,
        oc_map=oc_map,
        thread_pool_size=2,
        exclude_pattern="quay.io/redhat|quay.io/app-sre",
    )
    assert _to_set(images) == _to_set([
        {
            "name": "quay.io/prometheus/blackbox-exporter",
            "namespaces": "app-sre-observability-stage",
            "count": 1,
        },
        {
            "name": "registry.redhat.io/openshift-pipelines/pipelines-entrypoint-rhel8",
            "namespaces": "app-sre-pipelines",
            "count": 3,
        },
    ])


def testfetch_include_pattern(namespaces: list[NamespaceV1], oc_map: OCMap) -> None:
    images = fetch_pods_images_from_namespaces(
        namespaces=namespaces,
        oc_map=oc_map,
        thread_pool_size=2,
        include_pattern="^registry.redhat.io",
    )
    assert images == [
        {
            "name": "registry.redhat.io/openshift-pipelines/pipelines-entrypoint-rhel8",
            "namespaces": "app-sre-pipelines",
            "count": 3,
        },
    ]
