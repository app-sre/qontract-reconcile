from collections import defaultdict
from enum import Enum
from typing import (
    Generator,
    Optional,
)

from pydantic import BaseModel

from reconcile.utils.ocm.base import OCMModelLink
from reconcile.utils.ocm.labels import (
    OCMLabel,
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
    get_labels,
    get_organization_labels,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.subscriptions import (
    OCMCapability,
    build_subscription_filter,
    get_subscriptions,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


class OCMClusterState(Enum):
    ERROR = "error"
    HIBERNATING = "hibernating"
    INSTALLING = "installing"
    PENING = "pending"
    POWERING_DOWN = "powering_down"
    READY = "ready"
    RESUMING = "resuming"
    UNINSTALLING = "uninstalling"
    UNKNOWN = "unknown"
    VALIDATING = "validating"
    WAITING = "waiting"


class OCMCluster(BaseModel):

    kind: str = "Cluster"
    id: str
    external_id: str
    """
    This is sometimes also called the cluster UUID.
    """

    name: str
    display_name: str

    managed: bool

    openshift_version: str
    state: OCMClusterState

    subscription: OCMModelLink
    region: OCMModelLink
    cloud_provider: OCMModelLink
    product: OCMModelLink


class ClusterDetails(BaseModel):

    ocm_cluster: OCMCluster

    organization_id: str
    capabilities: dict[str, OCMCapability]
    """
    The capabilities of a cluster. They represent feature flags and are
    found on the subscription of a cluster.
    """

    subscription_labels: dict[str, OCMSubscriptionLabel]
    organization_labels: dict[str, OCMOrganizationLabel]

    def get_label(self, name: str) -> Optional[OCMLabel]:
        if name in self.subscription_labels:
            return self.subscription_labels[name]
        if name in self.organization_labels:
            return self.organization_labels[name]
        return None


def discover_clusters_by_labels(
    ocm_api: OCMBaseClient, label_filter: Filter
) -> list[ClusterDetails]:
    """
    Discover clusters in OCM by their subscription and organization labels.
    The discovery labels are defined via the label_filter argument.
    """
    subscription_ids = set()
    organization_ids = set()
    for label in get_labels(ocm_api=ocm_api, filter=label_filter):
        if isinstance(label, OCMSubscriptionLabel):
            subscription_ids.add(label.subscription_id)
        elif isinstance(label, OCMOrganizationLabel):
            organization_ids.add(label.organization_id)
    sub_id_filter = Filter().is_in("id", subscription_ids)
    org_id_filter = Filter().is_in("organization_id", organization_ids)
    subscription_filter = (
        sub_id_filter | org_id_filter  # pylint: disable=unsupported-binary-operation
    )
    # the pylint ignore above is because of a bug in pylint - https://github.com/PyCQA/pylint/issues/7381
    return list(
        get_cluster_details_for_subscriptions(
            ocm_api=ocm_api,
            subscription_filter=subscription_filter,
        )
    )


def discover_clusters_for_subscriptions(
    ocm_api: OCMBaseClient,
    subscription_ids: list[str],
    cluster_filter: Optional[Filter] = None,
) -> list[ClusterDetails]:
    """
    Discover clusters by filtering on their subscription IDs.
    Additionally, a cluster_filter can be applied to narrow the
    discovered clusters.
    """
    if not subscription_ids:
        return []

    return list(
        get_cluster_details_for_subscriptions(
            ocm_api=ocm_api,
            subscription_filter=Filter().is_in("id", subscription_ids),
            cluster_filter=cluster_filter,
        )
    )


def discover_clusters_for_organizations(
    ocm_api: OCMBaseClient,
    organization_ids: list[str],
    cluster_filter: Optional[Filter] = None,
) -> list[ClusterDetails]:
    """
    Discover clusters by filtering on their organization IDs.
    Additionally, a cluster_filter can be applied to narrow the
    discovered clusters.
    """
    if not organization_ids:
        return []

    return list(
        get_cluster_details_for_subscriptions(
            ocm_api=ocm_api,
            subscription_filter=Filter().is_in("organization_id", organization_ids),
            cluster_filter=cluster_filter,
        )
    )


def get_ocm_clusters(
    ocm_api: OCMBaseClient,
    cluster_filter: Filter,
) -> Generator[OCMCluster, None, None]:
    for cluster_dict in ocm_api.get_paginated(
        api_path="/api/clusters_mgmt/v1/clusters",
        params={"search": cluster_filter.render()},
        max_page_size=100,
    ):
        yield OCMCluster(**cluster_dict)


def get_cluster_details_for_subscriptions(
    ocm_api: OCMBaseClient,
    subscription_filter: Optional[Filter] = None,
    cluster_filter: Optional[Filter] = None,
) -> Generator[ClusterDetails, None, None]:
    """
    Discover clusters by filtering on their subscriptions. The subscription_filter
    can be used to restrict on any subscription field. Additionally, a cluster_filter
    can be applied to narrow the discovered clusters.
    """
    # get subscription details
    subscriptions = get_subscriptions(
        ocm_api=ocm_api,
        filter=(subscription_filter or Filter()) & build_subscription_filter(),
    )
    if not subscriptions:
        return

    # get organization labels
    organization_labels: dict[str, list[OCMOrganizationLabel]] = defaultdict(list)
    for label in get_organization_labels(
        ocm_api=ocm_api,
        filter=Filter().is_in(
            "organization_id",
            {s.organization_id for s in subscriptions.values()},
        ),
    ):
        organization_labels[label.organization_id].append(label)

    cluster_search_filter = (cluster_ready_for_app_interface() & cluster_filter).is_in(
        "subscription.id", subscriptions.keys()
    )
    for filter_chunk in cluster_search_filter.chunk_by(
        "subscription.id", 100, ignore_missing=True
    ):
        for cluster in get_ocm_clusters(ocm_api=ocm_api, cluster_filter=filter_chunk):
            subscription = subscriptions[cluster.subscription.id]
            yield ClusterDetails(
                ocm_cluster=cluster,
                organization_id=subscription.organization_id,
                capabilities={
                    capability.name: capability
                    for capability in subscription.capabilities or []
                },
                subscription_labels={
                    label.key: label for label in subscription.labels or []
                },
                organization_labels={
                    label.key: label
                    for label in organization_labels.get(subscription.organization_id)
                    or []
                },
            )


def cluster_ready_for_app_interface() -> Filter:
    """
    Filter for clusters that are considered ready for app-interface processing,
    which boils down to managed OSD/ROSA clusters in ready state.
    """
    return (
        Filter()
        .eq("managed", "true")
        .eq("state", OCMClusterState.READY.value)
        .is_in("product.id", ["osd", "rosa"])
    )
