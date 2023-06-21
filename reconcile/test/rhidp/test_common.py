from typing import Callable
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.rhidp.clusters import (
    ClusterAuthOIDCV1,
    ClusterV1,
    OpenShiftClusterManagerV1,
)
from reconcile.rhidp import common
from reconcile.test.ocm.fixtures import build_cluster_details
from reconcile.utils.ocm.labels import (
    LabelContainer,
    subscription_label_filter,
)

DiscoverClustersMock = Callable[[str, str], Mock]


@pytest.fixture
def discover_clusters_by_labels_mock(
    mocker: MockerFixture, build_cluster_rhidp_labels: LabelContainer
) -> DiscoverClustersMock:
    def _discover_clusters_by_labels_mock(cluster_name: str, org_id: str) -> Mock:
        m = mocker.patch.object(
            common,
            "discover_clusters_by_labels",
            autospec=True,
        )
        m.return_value = [
            build_cluster_details(
                cluster_name=cluster_name,
                subscription_labels=build_cluster_rhidp_labels,
                org_id=org_id,
            )
        ]
        return m

    return _discover_clusters_by_labels_mock


def test_rhidp_common_discover_clusters(
    discover_clusters_by_labels_mock: DiscoverClustersMock,
) -> None:
    org_id = "org-id"
    cluster_name = "cluster-1"

    mock = discover_clusters_by_labels_mock(cluster_name, org_id)

    clusters = common.discover_clusters(None, "org-id")  # type: ignore

    mock.assert_called_once_with(
        ocm_api=None,
        label_filter=subscription_label_filter()
        .eq("key", common.RHIDP_LABEL_KEY)
        .eq("value", "enabled"),
    )

    assert org_id in clusters
    assert len(clusters[org_id]) == 1
    assert clusters[org_id][0].ocm_cluster.name == cluster_name


def test_rhidp_common_discover_clusters_with_org_filter(
    discover_clusters_by_labels_mock: DiscoverClustersMock,
) -> None:
    org_id = "org-id"
    cluster_name = "cluster-1"

    discover_clusters_by_labels_mock(cluster_name, org_id)

    clusters = common.discover_clusters(None, {"org-id"})  # type: ignore
    assert org_id in clusters

    clusters = common.discover_clusters(None, {"another-org-id"})  # type: ignore
    assert org_id not in clusters


def test_rhidp_common_discover_clusters_without_org_filter(
    discover_clusters_by_labels_mock: DiscoverClustersMock,
) -> None:
    org_id = "org-id"
    cluster_name = "cluster-1"

    discover_clusters_by_labels_mock(cluster_name, org_id)

    clusters = common.discover_clusters(None, None)  # type: ignore

    assert org_id in clusters


def test_rhidp_common_build_cluster_obj(
    ocm_env: OCMEnvironment, build_cluster_rhidp_labels: LabelContainer
) -> None:
    cluster_details = build_cluster_details(
        cluster_name="cluster_name",
        subscription_labels=build_cluster_rhidp_labels,
        org_id="org_id",
    )
    assert common.build_cluster_obj(
        ocm_env,
        cluster_details,
        auth_name="auth_name",
        auth_issuer_url="https://foobar.com",
    ) == ClusterV1(
        name="cluster_name",
        consoleUrl="https://console.foobar.com",
        ocm=OpenShiftClusterManagerV1(
            name="",
            environment=OCMEnvironment(
                name="env",
                url="https://ocm",
                accessTokenClientId="client-id",
                accessTokenUrl="https://sso/token",
                accessTokenClientSecret=VaultSecret(
                    path="path", field="client-secret", version=None, format=None
                ),
            ),
            orgId="org_id",
            accessTokenClientId=None,
            accessTokenUrl=None,
            accessTokenClientSecret=None,
            blockedVersions=None,
            sectors=None,
        ),
        upgradePolicy=None,
        disable=None,
        auth=[
            ClusterAuthOIDCV1(
                service="oidc",
                name="auth_name",
                issuer="https://foobar.com",
                claims=None,
            )
        ],
    )
