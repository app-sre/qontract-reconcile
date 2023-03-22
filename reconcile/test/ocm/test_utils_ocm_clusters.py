from typing import Optional

import httpretty as httpretty_module
from pytest_mock import MockerFixture

from reconcile.test.ocm.conftest import register_ocm_get_list_request
from reconcile.test.ocm.test_utils_ocm_labels import (
    build_organization_label,
    build_subscription_label,
)
from reconcile.test.ocm.test_utils_ocm_subscriptions import build_ocm_subscription
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.ocm import (
    clusters,
    subscriptions,
)
from reconcile.utils.ocm.clusters import (
    OCMCluster,
    OCMClusterState,
    discover_clusters_by_labels,
    discover_clusters_for_organizations,
    discover_clusters_for_subscriptions,
    get_clusters_for_subscriptions,
)
from reconcile.utils.ocm.labels import (
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
    label_filter,
)
from reconcile.utils.ocm.search_filters import (
    Filter,
    or_filter,
)


def build_cluster(
    name: str,
    org_id: str = "org_id",
    subs_id: str = "subs_id",
    org_labels: Optional[list[tuple[str, str]]] = None,
    subs_labels: Optional[list[tuple[str, str]]] = None,
) -> OCMCluster:
    return OCMCluster(
        id=f"{name}_id",
        external_id=f"{name}_external_id",
        name=name,
        display_name=f"{name}_display_name",
        subscription_id=subs_id,
        organization_id=org_id,
        organization_labels={
            k: build_organization_label(k, v, org_id) for k, v in org_labels or []
        },
        subscription_labels={
            k: build_subscription_label(k, v, subs_id) for k, v in subs_labels or []
        },
        capabilities=[],
        api_url="https://api.example.com",
        console_url="https://console.example.com",
        state=OCMClusterState.READY,
        openshift_version="4.12.0",
        product_id="OCP",
        region_id="us-east-1",
    )


def test_utils_ocm_discover_clusters_for_subscriptions(
    ocm_api: OCMBaseClient, mocker: MockerFixture
):
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_clusters_for_subscriptions"
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
):
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_clusters_for_subscriptions"
    )
    assert not discover_clusters_for_subscriptions(
        ocm_api,
        [],
    )

    get_clusters_for_subscriptions_mock.assert_not_called()


def test_utils_ocm_discover_clusters_for_organizations(
    ocm_api: OCMBaseClient, mocker: MockerFixture
):
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_clusters_for_subscriptions"
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
):
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_clusters_for_subscriptions"
    )
    assert not discover_clusters_for_organizations(
        ocm_api,
        [],
    )

    get_clusters_for_subscriptions_mock.assert_not_called()


def test_discover_clusters_by_labels(
    mocker: MockerFixture, ocm_api: OCMBaseClient, httpretty: httpretty_module
):
    """
    Tests that the discover_clusters_by_labels function discovers subscription and
    organization labels properly and calls get_clusters_for_subscriptions with
    an appropriate subscription and organization filter.
    """
    # prepare mocks
    get_clusters_for_subscriptions_mock = mocker.patch.object(
        clusters, "get_clusters_for_subscriptions"
    )

    register_ocm_get_list_request(
        ocm_api,
        httpretty,
        "/api/accounts_mgmt/v1/labels",
        [
            build_subscription_label("label", "subs_value", "sub_id").dict(
                by_alias=True
            ),
            build_subscription_label("label", "subs_value", "sub_id_2").dict(
                by_alias=True
            ),
            build_organization_label("label", "org_value", "org_id").dict(
                by_alias=True
            ),
        ],
    )

    # call discovery
    discover_clusters_by_labels(
        ocm_api,
        label_filter=label_filter(key="label"),
    )

    # check that get_clusters_for_subscriptions was called with a proper
    # subscription filter
    get_clusters_for_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        subscription_filter=or_filter(
            Filter().is_in("id", ["sub_id", "sub_id_2"]),
            Filter().is_in("organization_id", ["org_id"]),
        ),
    )


def test_get_clusters_for_subscriptions(
    mocker: MockerFixture, ocm_api: OCMBaseClient, httpretty: httpretty_module
):
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
    get_organization_labels_mock.return_value = iter(
        [
            organization_label,
            build_organization_label("org_label", "value", "another_org_id"),
        ]
    )

    register_ocm_get_list_request(
        ocm_api,
        httpretty,
        "/api/clusters_mgmt/v1/clusters",
        [
            {
                "id": "cl1",
                "name": "cl1",
                "display_name": "cl1",
                "state": "ready",
                "openshift_version": "4.12.0",
                "external_id": "external_id",
                "subscription": {"id": subscription_id},
                "product": {"id": "OCP"},
                "region": {"id": "us-east-1"},
                "api": {"url": "https://api.clusters.example.com:6443"},
                "console": {
                    "url": "https://console-openshift-console.apps.clusters.example.com"
                },
            }
        ],
    )

    subscription_filter = Filter().eq("id", subscription_id)
    discoverd_clusters = get_clusters_for_subscriptions(
        ocm_api=ocm_api,
        subscription_filter=subscription_filter,
    )

    get_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        filter=subscription_filter.combine(subscriptions.build_subscription_filter()),
    )

    get_organization_labels_mock.assert_called_once_with(
        ocm_api=ocm_api, filter=Filter().is_in("organization_id", [organization_id])
    )

    assert subscription_id in discoverd_clusters
    assert discoverd_clusters[subscription_id].organization_labels == {
        organization_label.key: organization_label
    }
    assert discoverd_clusters[subscription_id].subscription_labels == {
        sl.key: sl for sl in subscription.labels or []
    }


def test_get_clusters_for_subscriptions_none_found(
    mocker: MockerFixture, ocm_api: OCMBaseClient, httpretty: httpretty_module
):

    get_subscriptions_mock = mocker.patch.object(clusters, "get_subscriptions")
    get_subscriptions_mock.return_value = {}

    subscription_filter = Filter().eq("id", "sub_id")
    discoverd_clusters = get_clusters_for_subscriptions(
        ocm_api=ocm_api,
        subscription_filter=subscription_filter,
    )

    assert not discoverd_clusters

    get_subscriptions_mock.assert_called_once_with(
        ocm_api=ocm_api,
        filter=subscription_filter.combine(subscriptions.build_subscription_filter()),
    )


def test_ocm_cluster_get_label():
    cluster = build_cluster(
        name="cl",
        org_labels=[("org_label", "org_value"), ("label", "org_value")],
        subs_labels=[("subs_label", "subs_value"), ("label", "subs_value")],
    )

    org_label = cluster.get_label("org_label")
    assert isinstance(org_label, OCMOrganizationLabel)
    assert org_label.key == "org_label"
    assert org_label.value == "org_value"

    subs_label = cluster.get_label("subs_label")
    assert isinstance(subs_label, OCMSubscriptionLabel)
    assert subs_label.key == "subs_label"
    assert subs_label.value == "subs_value"

    label = cluster.get_label("label")
    assert isinstance(label, OCMSubscriptionLabel)
    assert label.key == "label"
    assert label.value == "subs_value"

    assert cluster.get_label("missing-label") is None
