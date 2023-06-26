from collections.abc import (
    Generator,
    Iterable,
)
from datetime import datetime
from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)

from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


def get_subscription_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator["OCMSubscriptionLabel", None, None]:
    """
    Finds all subscription labels that match the given filter.
    """
    for subscription_label in get_labels(
        ocm_api=ocm_api, filter=filter & subscription_label_filter()
    ):
        if isinstance(subscription_label, OCMSubscriptionLabel):
            yield subscription_label


def subscription_label_filter() -> Filter:
    """
    Returns a filter that can be used to find only subscription labels.
    """
    return Filter().eq("type", "Subscription")


def get_organization_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator["OCMOrganizationLabel", None, None]:
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
) -> Generator["OCMLabel", None, None]:
    """
    Finds all labels that match the given filter.
    """
    for label_dict in ocm_api.get_paginated(
        api_path="/api/accounts_mgmt/v1/labels",
        params={"search": filter.render()},
    ):
        yield build_label_from_dict(label_dict)


def build_label_from_dict(label_dict: dict[str, Any]) -> "OCMLabel":
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


class OCMLabel(BaseModel):
    """
    Represents a general label without any type specific information.
    See subclasses for type specific information.
    """

    id: str
    internal: bool
    updated_at: datetime
    created_at: datetime
    href: str
    key: str
    value: str
    type: str
    """
    The type of the label, e.g. Subscription, Organization, Account.
    See subclasses.
    """


class OCMOrganizationLabel(OCMLabel):
    """
    Represents a label attached to an organization.
    """

    organization_id: str


class OCMSubscriptionLabel(OCMLabel):
    """
    Represents a label attached to a subscription.
    """

    subscription_id: str


class OCMAccountLabel(OCMLabel):
    """
    Represents a label attached to an account.
    """

    account_id: str


class LabelContainer(BaseModel):
    """
    A container for a set of labels with some convenience methods to work
    efficiently with them.
    """

    labels: dict[str, OCMLabel] = Field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.labels)

    def __bool__(self) -> bool:
        return len(self.labels) > 0

    def get(self, name: str) -> Optional[OCMLabel]:
        return self.labels.get(name)

    def get_required_label(self, name: str) -> OCMLabel:
        label = self.get(name)
        if not label:
            raise ValueError(f"Required label '{name}' does not exist.")
        return label

    def get_label_value(self, name: str) -> Optional[str]:
        label = self.get(name)
        if label:
            return label.value
        return None

    def get_values_dict(self) -> dict[str, str]:
        return {label.key: label.value for label in self.labels.values()}


def build_label_container(
    *label_iterables: Optional[Iterable[OCMLabel]],
) -> LabelContainer:
    """
    Builds a label container from a list of labels.
    """
    merged_labels = {}
    for labels in label_iterables:
        for label in labels or []:
            merged_labels[label.key] = label
    return LabelContainer(labels=merged_labels)


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
