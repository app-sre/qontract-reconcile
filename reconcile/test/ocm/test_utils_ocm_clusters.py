from collections.abc import Callable

from pytest_httpserver import HTTPServer
from pytest_mock import (
    MockerFixture,
    MockFixture,
)

from reconcile.test.ocm.fixtures import (
    OcmUrl,
    build_ocm_cluster,
)
from reconcile.test.ocm.test_utils_ocm_labels import (
    build_organization_label,
    build_subscription_label,
)
from reconcile.test.ocm.test_utils_ocm_subscriptions import build_ocm_subscription
from reconcile.utils.ocm import (
    clusters,
    subscriptions,
)
from reconcile.utils.ocm.base import (
    ACTIVE_SUBSCRIPTION_STATES,
    ClusterDetails,
    OCMCluster,
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
    build_label_container,
)
from reconcile.utils.ocm.clusters import (
    discover_clusters_by_labels,
    discover_clusters_for_organizations,
    discover_clusters_for_subscriptions,
    get_cluster_details_for_subscriptions,
    get_node_pools,
    get_version,
)
from reconcile.utils.ocm.labels import label_filter
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_cluster_details(
    ocm_cluster: OCMCluster,
    org_id: str = "org_id",
    org_labels: list[tuple[str, str]] | None = None,
    subs_labels: list[tuple[str, str]] | None = None,
) -> ClusterDetails:
    return ClusterDetails(
        ocm_cluster=ocm_cluster,
        organization_id=org_id,
        organization_labels=build_label_container([
            build_organization_label(k, v, org_id) for k, v in org_labels or []
        ]),
        subscription_labels=build_label_container(
            [
                build_subscription_label(k, v, ocm_cluster.subscription.id)
                for k, v in subs_labels or []
            ],
        ),
        capabilities=[],
    )


def test_utils_ocm_discover_clusters_for_subscriptions(
    ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_cluster_details_for_subscriptions"
    )
    discover_clusters_for_subscriptions(
        ocm_api,
        ["sub1", "sub2"],
    )

    get_clusters_for_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        subscription_filter=Filter().is_in("id", ["sub1", "sub2"]),
        cluster_filter=None,
    )


def test_utils_ocm_discover_clusters_for_empty_subscriptions_id_list(
    ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_cluster_details_for_subscriptions"
    )
    assert not discover_clusters_for_subscriptions(
        ocm_api,
        [],
    )

    get_clusters_for_subscriptions_mock.assert_not_called()


def test_utils_ocm_discover_clusters_for_organizations(
    ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_cluster_details_for_subscriptions"
    )
    discover_clusters_for_organizations(
        ocm_api,
        ["org1", "org2"],
    )

    get_clusters_for_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        subscription_filter=Filter().is_in("organization_id", ["org1", "org2"]),
        cluster_filter=None,
    )


def test_utils_ocm_discover_clusters_for_empty_organization_id_list(
    ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_cluster_details_for_subscriptions"
    )
    assert not discover_clusters_for_organizations(
        ocm_api,
        [],
    )

    get_clusters_for_subscriptions_mock.assert_not_called()


def test_discover_clusters_by_labels(
    mocker: MockerFixture,
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    """
    Tests that the discover_clusters_by_labels function discovers subscription and
    organization labels properly and calls get_clusters_for_subscriptions with
    an appropriate subscription and organization filter.
    """
    # prepare mocks
    org_id = "org_id"
    sub_id = "sub_id"
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_cluster_details_for_subscriptions"
    )
    get_clusters_for_subscriptions_mock.return_value = iter([
        build_cluster_details(
            ocm_cluster=build_ocm_cluster("cluster_id", sub_id),
            org_id=org_id,
        )
    ])

    register_ocm_url_responses([
        OcmUrl(
            method="GET",
            uri="/api/accounts_mgmt/v1/labels",
        ).add_list_response([
            build_subscription_label("label", "subs_value", sub_id).dict(by_alias=True),
            build_subscription_label("label", "subs_value", "sub_id_2").dict(
                by_alias=True
            ),
            build_organization_label("label", "org_value", org_id).dict(by_alias=True),
        ])
    ])

    # call discovery
    discovered_clusters = discover_clusters_by_labels(
        ocm_api,
        label_filter=label_filter(key="label"),
    )

    # validate cluster composition
    assert len(discovered_clusters) == 1
    assert len(discovered_clusters[0].labels) == 1
    assert (
        discovered_clusters[0].labels.get_required_label("label").value == "subs_value"
    )

    # check that get_clusters_for_subscriptions was called with a proper
    # subscription filter
    get_clusters_for_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        subscription_filter=(
            Filter().is_in(  # pylint: disable=unsupported-binary-operation
                "id", ["sub_id", "sub_id_2"]
            )
            | Filter().is_in("organization_id", ["org_id"])
        ),
    )


def test_get_clusters_for_subscriptions(
    mocker: MockerFixture,
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    httpserver: HTTPServer,
) -> None:
    """
    Tests the subscription and organization labels are properly queried
    and returned in the context of a cluster.
    """
    subscription_id = "sub_id"
    organization_id = "org_id"
    subscription = build_ocm_subscription(
        subscription_id, organization_id, labels=[("sub_label", "value")]
    )
    organization_label = build_organization_label("org_label", "value", organization_id)
    get_subscriptions_mock = mocker.patch.object(clusters, "get_subscriptions")
    get_subscriptions_mock.return_value = {subscription_id: subscription}

    get_organization_labels_mock = mocker.patch.object(
        clusters, "get_organization_labels"
    )
    get_organization_labels_mock.return_value = iter([
        organization_label,
        build_organization_label("org_label", "value", "another_org_id"),
    ])

    # clear default /api/clusters_mgmt/v1/clusters request handler
    httpserver.clear_all_handlers()
    register_ocm_url_responses([
        OcmUrl(method="GET", uri="/api/clusters_mgmt/v1/clusters").add_list_response([
            build_ocm_cluster(
                name="cl1",
                subs_id=subscription_id,
            )
        ])
    ])

    subscription_filter = Filter().eq("id", subscription_id)
    discoverd_clusters = list(
        get_cluster_details_for_subscriptions(
            ocm_api=ocm_api, subscription_filter=subscription_filter, init_labels=True
        )
    )
    assert len(discoverd_clusters) == 1

    get_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        filter=subscription_filter
        & subscriptions.build_subscription_filter(states=ACTIVE_SUBSCRIPTION_STATES),
    )
    get_organization_labels_mock.assert_called_once_with(
        ocm_api=ocm_api, filter=Filter().is_in("organization_id", [organization_id])
    )

    assert (
        discoverd_clusters[0].labels.get_label_value(organization_label.key)
        == organization_label.value
    )

    for sl in subscription.labels or []:
        assert discoverd_clusters[0].labels.get_label_value(sl.key) == sl.value


def test_get_clusters_for_subscriptions_none_found(
    mocker: MockerFixture, ocm_api: OCMBaseClient
) -> None:
    get_subscriptions_mock = mocker.patch.object(clusters, "get_subscriptions")
    get_subscriptions_mock.return_value = {}

    subscription_filter = Filter().eq("id", "sub_id")
    discoverd_clusters = list(
        get_cluster_details_for_subscriptions(
            ocm_api=ocm_api,
            subscription_filter=subscription_filter,
        )
    )

    assert not discoverd_clusters

    get_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        filter=subscription_filter
        & subscriptions.build_subscription_filter(states=ACTIVE_SUBSCRIPTION_STATES),
    )


def test_ocm_cluster_get_label() -> None:
    cluster = build_cluster_details(
        ocm_cluster=build_ocm_cluster(name="cl"),
        org_labels=[("org_label", "org_value"), ("label", "org_value")],
        subs_labels=[("subs_label", "subs_value"), ("label", "subs_value")],
    )

    org_label = cluster.labels.get("org_label")
    assert isinstance(org_label, OCMOrganizationLabel)
    assert org_label.key == "org_label"
    assert org_label.value == "org_value"

    subs_label = cluster.labels.get("subs_label")
    assert isinstance(subs_label, OCMSubscriptionLabel)
    assert subs_label.key == "subs_label"
    assert subs_label.value == "subs_value"

    label = cluster.labels.get("label")
    assert isinstance(label, OCMSubscriptionLabel)
    assert label.key == "label"
    assert label.value == "subs_value"

    assert cluster.labels.get("missing-label") is None


def test_get_node_pools(mocker: MockFixture) -> None:
    node_pool = {
        "id": "np1",
        "instance_type": "m5.2xlarge",
        "replicas": 3,
        "foo": "bar",
    }
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.get_paginated.return_value = iter([node_pool])

    node_pools = get_node_pools(ocm, "fooo")
    assert len(node_pools) == 1
    assert node_pools[0]["id"] == node_pool["id"]
    assert node_pools[0]["instance_type"] == node_pool["instance_type"]
    assert node_pools[0]["replicas"] == node_pool["replicas"]
    assert "foo" not in node_pools[0]


def test_get_version(mocker: MockFixture) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.get.return_value = {}

    version = get_version(ocm, "test")
    assert len(version) == 0

    version_return = {"id": "openshift-v4.12.16", "raw_id": "4.12.16", "foo": "bar"}
    ocm.get.return_value = version_return

    version = get_version(ocm, "fooo")
    assert version["id"] == version_return["id"]
    assert version["raw_id"] == version_return["raw_id"]
    assert "foo" not in version
