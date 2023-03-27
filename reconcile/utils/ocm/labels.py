from datetime import datetime
from typing import (
    Any,
    Generator,
    Optional,
)

from pydantic import BaseModel

from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


def get_subscription_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator["OCMSubscriptionLabel", None, None]:
    """
    Finds all subscription labels that match the given filter.
    """
    for subscription_label in get_labels(
        ocm_api=ocm_api, filter=filter.eq("type", "Subscription")
    ):
        if isinstance(subscription_label, OCMSubscriptionLabel):
            yield subscription_label


def get_organization_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator["OCMOrganizationLabel", None, None]:
    """
    Finds all organization labels that match the given filter.
    """
    for org_label in get_labels(
        ocm_api=ocm_api, filter=filter.eq("type", "Organization")
    ):
        if isinstance(org_label, OCMOrganizationLabel):
            yield org_label


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


def label_filter(key: str, value: Optional[str] = None) -> Filter:
    """
    Creates a filter that matches a label with the given key and
    optionally a value.
    """
    lf = Filter().eq("key", key)
    if value:
        return lf.eq("value", value)
    return lf
