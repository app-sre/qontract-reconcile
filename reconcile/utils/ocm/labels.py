from collections.abc import (
    Generator,
    Iterable,
    Mapping,
)
from typing import (
    Any,
    Optional,
)

from reconcile.utils.ocm.base import (
    ClusterDetails,
    LabelContainer,
    OCMAccountLabel,
    OCMLabel,
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


def get_subscription_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator[OCMSubscriptionLabel, None, None]:
    """
    Finds all subscription labels that match the given filter.
    """
    for subscription_label in get_labels(
        ocm_api=ocm_api, filter=filter & subscription_label_filter()
    ):
        if isinstance(subscription_label, OCMSubscriptionLabel):
            yield subscription_label


def add_subscription_labels(
    ocm_api: OCMBaseClient,
    cluster: ClusterDetails,
    labels: Mapping[str, str],
) -> None:
    """Add the given labels to the cluster subscription."""
    for key, value in labels.items():
        ocm_api.post(
            api_path=f"{cluster.ocm_cluster.subscription.href}/labels",
            data={"kind": "Label", "key": key, "value": value},
        )


def update_subscription_labels(
    ocm_api: OCMBaseClient,
    cluster: ClusterDetails,
    labels: Mapping[str, str],
) -> None:
    """Update the given labels in the cluster subscription."""
    for key, value in labels.items():
        ocm_api.patch(
            api_path=cluster.labels[key].href,
            data={"kind": "Label", "key": key, "value": value},
        )


def delete_subscription_labels(
    ocm_api: OCMBaseClient,
    cluster: ClusterDetails,
    labels: Iterable[str],
) -> None:
    """Delete the given labels from the cluster subscription."""
    for label in labels:
        ocm_api.delete(api_path=cluster.labels[label].href)


def subscription_label_filter() -> Filter:
    """
    Returns a filter that can be used to find only subscription labels.
    """
    return Filter().eq("type", "Subscription")


def get_organization_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator[OCMOrganizationLabel, None, None]:
    """
    Finds all organization labels that match the given filter.
    """
    for org_label in get_labels(
        ocm_api=ocm_api, filter=filter & organization_label_filter()
    ):
        if isinstance(org_label, OCMOrganizationLabel):
            yield org_label


def organization_label_filter() -> Filter:
    """
    Returns a filter that can be used to find only organization labels.
    """
    return Filter().eq("type", "Organization")


def get_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator[OCMLabel, None, None]:
    """
    Finds all labels that match the given filter.
    """
    for label_dict in ocm_api.get_paginated(
        api_path="/api/accounts_mgmt/v1/labels",
        params={"search": filter.render()},
    ):
        yield build_label_from_dict(label_dict)


def build_label_from_dict(label_dict: dict[str, Any]) -> OCMLabel:
    """
    Translates a label dict into a type specific label object.
    """
    label_type = label_dict.get("type")
    if label_type == "Subscription":
        return OCMSubscriptionLabel(**label_dict)
    if label_type == "Organization":
        return OCMOrganizationLabel(**label_dict)
    if label_type == "Account":
        return OCMAccountLabel(**label_dict)
    raise ValueError(f"Unknown label type: {label_dict['type']}")


def build_container_for_prefix(
    container: LabelContainer, key_prefix: str, strip_key_prefix: bool = False
) -> "LabelContainer":
    """
    Builds a new label container with all labels that have the given prefix.
    """

    def strip_prefix_if_needed(key: str) -> str:
        if strip_key_prefix:
            return key[len(key_prefix) :]
        return key

    return LabelContainer(
        labels={
            strip_prefix_if_needed(label.key): label.copy(
                update={"key": strip_prefix_if_needed(label.key)}
            )
            for label in container.labels.values()
            if label.key.startswith(key_prefix)
        }
    )


def label_filter(key: str, value: Optional[str] = None) -> Filter:
    """
    Creates a filter that matches a label with the given key and
    optionally a value.
    """
    lf = Filter().eq("key", key)
    if value:
        return lf.eq("value", value)
    return lf
