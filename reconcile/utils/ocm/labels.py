from collections import defaultdict
from collections.abc import Generator
from typing import Any

from reconcile.utils.ocm.base import (
    LabelContainer,
    OCMAccountLabel,
    OCMCluster,
    OCMLabel,
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
    build_label_container,
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


def add_subscription_label(
    ocm_api: OCMBaseClient,
    ocm_cluster: OCMCluster,
    label: str,
    value: str,
) -> None:
    """Add the given label to the cluster subscription."""
    add_label(
        ocm_api=ocm_api,
        label_container_href=f"{ocm_cluster.subscription.href}/labels",
        label=label,
        value=value,
    )


def add_label(
    ocm_api: OCMBaseClient,
    label_container_href: str,
    label: str,
    value: str,
) -> None:
    """Add the given label to the cluster subscription."""
    ocm_api.post(
        api_path=label_container_href,
        data={"kind": "Label", "key": label, "value": value},
    )


def update_ocm_label(
    ocm_api: OCMBaseClient,
    ocm_label: OCMLabel,
    value: str,
) -> None:
    """Update the label value in the given OCM label."""
    ocm_api.patch(
        api_path=ocm_label.href,
        data={"kind": "Label", "key": ocm_label.key, "value": value},
    )


def update_label(
    ocm_api: OCMBaseClient,
    label_container_href: str,
    label: str,
    value: str,
) -> None:
    """Update the label value in the given OCM label."""
    ocm_api.patch(
        api_path=f"{label_container_href}/{label}",
        data={"kind": "Label", "key": label, "value": value},
    )


def delete_ocm_label(ocm_api: OCMBaseClient, ocm_label: OCMLabel) -> None:
    """Delete the given OCM label."""
    ocm_api.delete(api_path=ocm_label.href)


def delete_label(ocm_api: OCMBaseClient, label_container_href: str, label: str) -> None:
    """Delete the given OCM label."""
    ocm_api.delete(api_path=f"{label_container_href}/{label}")


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
        params={"search": filter.render(), "orderBy": "created_at"},
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


def label_filter(key: str, value: str | None = None) -> Filter:
    """
    Creates a filter that matches a label with the given key and
    optionally a value.
    """
    lf = Filter().eq("key", key)
    if value:
        return lf.eq("value", value)
    return lf


def get_org_labels(
    ocm_api: OCMBaseClient, org_ids: set[str], label_filter: Filter | None
) -> dict[str, LabelContainer]:
    """
    Fetch all labels from organizations. Optionally, label filtering can be
    performed via the `label_filter` parameter.

    The result is a dict with organization IDs as keys and label containers as values.
    """
    filter = Filter().is_in("organization_id", org_ids)
    if label_filter:
        filter &= label_filter
    labels_by_org: dict[str, list[OCMOrganizationLabel]] = defaultdict(list)
    for label in get_organization_labels(ocm_api, filter):
        labels_by_org[label.organization_id].append(label)
    return {
        org_id: build_label_container(labels)
        for org_id, labels in labels_by_org.items()
    }


def build_organization_labels_href(org_id: str) -> str:
    return f"/api/accounts_mgmt/v1/organizations/{org_id}/labels"
