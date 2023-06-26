from collections import defaultdict
from enum import Enum
from typing import (
    Generator,
    Optional,
)

from pydantic import BaseModel

from reconcile.utils.ocm.base import OCMModelLink
from reconcile.utils.ocm.labels import (
    LabelContainer,
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
    build_label_container,
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

ACTIVE_SUBSCRIPTION_STATES = {"Active", "Reserved"}
CAPABILITY_MANAGE_CLUSTER_ADMIN = "capability.cluster.manage_cluster_admin"


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


class OCMClusterFlag(BaseModel):
    enabled: bool


class OCMClusterAWSSettings(BaseModel):
    sts: Optional[OCMClusterFlag]

    @property
    def sts_enabled(self) -> bool:
        return self.sts is not None and self.sts.enabled


class OCMClusterVersion(BaseModel):
    id: str
    raw_id: str


class OCMClusterConsole(BaseModel):
    url: str


PRODUCT_ID_OSD = "osd"
PRODUCT_ID_ROSA = "rosa"


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
    state: OCMClusterState

    subscription: OCMModelLink
    region: OCMModelLink
    cloud_provider: OCMModelLink
    product: OCMModelLink

    aws: Optional[OCMClusterAWSSettings]

    version: OCMClusterVersion

    hypershift: OCMClusterFlag

    console: OCMClusterConsole

    def is_osd(self) -> bool:
        return self.product.id == PRODUCT_ID_OSD

    def is_rosa_classic(self) -> bool:
        return self.product.id == PRODUCT_ID_ROSA and not self.hypershift.enabled

    def is_rosa_hypershift(self) -> bool:
        return self.product.id == PRODUCT_ID_ROSA and self.hypershift.enabled


class ClusterDetails(BaseModel):
    ocm_cluster: OCMCluster

    organization_id: str
    capabilities: dict[str, OCMCapability]
    """
    The capabilities of a cluster. They represent feature flags and are
    found on the subscription of a cluster.
    """

    subscription_labels: LabelContainer
    organization_labels: LabelContainer

    @property
    def labels(self) -> LabelContainer:
        return build_label_container(
            self.organization_labels.labels.values(),
            self.subscription_labels.labels.values(),
        )

    def is_capability_set(self, name: str, value: str) -> bool:
        capa = self.capabilities.get(name)
        return capa is not None and capa.value == value


def discover_clusters_by_labels(
    ocm_api: OCMBaseClient, label_filter: Filter
) -> list[ClusterDetails]:
    """
    Discover clusters in OCM by their subscription and organization labels.
    The discovery labels are defined via the label_filter argument.
    """
    subscription_labels: dict[str, list[OCMSubscriptionLabel]] = defaultdict(list)
    organization_labels: dict[str, list[OCMOrganizationLabel]] = defaultdict(list)

    for label in get_labels(ocm_api=ocm_api, filter=label_filter):
        if isinstance(label, OCMSubscriptionLabel):
            subscription_labels[label.subscription_id].append(label)
        elif isinstance(label, OCMOrganizationLabel):
            organization_labels[label.organization_id].append(label)
    if not subscription_labels and not organization_labels:
        return []

    sub_id_filter = Filter().is_in("id", subscription_labels.keys())
    org_id_filter = Filter().is_in("organization_id", organization_labels.keys())
    subscription_filter = (
        sub_id_filter | org_id_filter  # pylint: disable=unsupported-binary-operation
    )
    # the pylint ignore above is because of a bug in pylint - https://github.com/PyCQA/pylint/issues/7381

    clusters = list(
        get_cluster_details_for_subscriptions(
            ocm_api=ocm_api,
            subscription_filter=subscription_filter,
        )
    )

    # fill in labels
    for cluster in clusters:
        cluster.subscription_labels = build_label_container(
            subscription_labels[cluster.ocm_cluster.subscription.id]
        )
        cluster.organization_labels = build_label_container(
            organization_labels[cluster.organization_id]
        )

    return clusters


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
    init_labels: bool = False,
) -> Generator[ClusterDetails, None, None]:
    """
    Discover clusters by filtering on their subscriptions. The subscription_filter
    can be used to restrict on any subscription field. Additionally, a cluster_filter
    can be applied to narrow the discovered clusters.
    """
    # get subscription details
    subscriptions = get_subscriptions(
        ocm_api=ocm_api,
        filter=(subscription_filter or Filter())
        & build_subscription_filter(states=ACTIVE_SUBSCRIPTION_STATES, managed=True),
    )
    if not subscriptions:
        return

    # get organization labels
    organization_labels: dict[str, list[OCMOrganizationLabel]] = defaultdict(list)
    if init_labels:
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
                organization_labels=build_label_container(
                    organization_labels.get(subscription.organization_id) or []
                ),
                subscription_labels=build_label_container(
                    (subscription.labels or []) if init_labels else []
                ),
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
        .is_in("product.id", [PRODUCT_ID_OSD, PRODUCT_ID_ROSA])
    )
