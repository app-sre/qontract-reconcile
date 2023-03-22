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
    for subscription_label in get_labels(
        ocm_api=ocm_api, filter=filter.eq("type", "Subscription")
    ):
        if isinstance(subscription_label, OCMSubscriptionLabel):
            yield subscription_label


def get_organization_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator["OCMOrganizationLabel", None, None]:
    for org_label in get_labels(
        ocm_api=ocm_api, filter=filter.eq("type", "Organization")
    ):
        if isinstance(org_label, OCMOrganizationLabel):
            yield org_label


def get_labels(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator["OCMLabel", None, None]:
    for label_dict in ocm_api.get_paginated(
        api_path="/api/accounts_mgmt/v1/labels",
        params={"search": filter.render()},
    ):
        yield build_label_from_dict(label_dict)


def build_label_from_dict(label_dict: dict[str, Any]) -> "OCMLabel":
    if label_dict["type"] == "Subscription":
        return OCMSubscriptionLabel(**label_dict)
    if label_dict["type"] == "Organization":
        return OCMOrganizationLabel(**label_dict)
    if label_dict["type"] == "Account":
        return OCMAccountLabel(**label_dict)
    raise ValueError(f"Unknown label type: {label_dict['type']}")


class OCMLabel(BaseModel):

    id: str
    internal: bool
    updated_at: datetime
    created_at: datetime
    href: str
    key: str
    value: str
    type: str


class OCMOrganizationLabel(OCMLabel):

    organization_id: str


class OCMSubscriptionLabel(OCMLabel):

    subscription_id: str


class OCMAccountLabel(OCMLabel):

    account_id: str


def label_filter(key: str, value: Optional[str] = None) -> Filter:
    lf = Filter().eq("key", key)
    if value:
        return lf.eq("value", value)
    return lf
