from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    ValidationError,
)

from reconcile.utils.ocm.labels import (
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


class OCMCapability(BaseModel):
    """
    Represents a capability (feature/feature flag) of a subscription, e.g. becoming cluster admin
    """

    name: str
    value: str


class OCMSubscriptionStatus(Enum):
    Active = "Active"
    Deprovisioned = "Deprovisioned"
    Stale = "Stale"
    Archived = "Archived"
    Reserved = "Reserved"
    Disconnected = "Disconnected"


class OCMSubscription(BaseModel):
    """
    Represents a subscription in OCM.
    """

    id: str
    href: str
    display_name: str
    created_at: datetime
    cluster_id: str

    organization_id: str
    managed: bool
    """
    A managed subscription is one that belongs to a cluster managed by OCM,
    e.g. ROSA, OSD, etc.
    """

    status: OCMSubscriptionStatus

    labels: Optional[list[OCMSubscriptionLabel]] = None
    capabilities: Optional[list[OCMCapability]] = None
    """
    Capabilities are a list of features/features flags that are enabled for a subscription.
    """


def get_subscriptions(
    ocm_api: OCMBaseClient, filter: Filter
) -> dict[str, OCMSubscription]:
    """
    Returns a dictionary of subscriptions based on the provided filter.
    The result is keyed by subscription ID.
    """
    subscriptions = {}
    chunk_size = 100
    for filter_chunk in filter.chunk_by("id", chunk_size, ignore_missing=True):
        for subscription_dict in ocm_api.get_paginated(
            api_path="/api/accounts_mgmt/v1/subscriptions?fetchCapabilities=true&fetchLabels=true",
            params={"search": filter_chunk.render()},
            max_page_size=chunk_size,
        ):
            try:
                sub = OCMSubscription(
                    **subscription_dict,
                )
                subscriptions[sub.id] = sub
            except ValidationError:
                pass
                # ignore subscriptions that fail to validate
                # against the OCMSubscription, since the lack important fields
    return subscriptions


def build_subscription_filter(
    states: Optional[set[str]] = None, managed: bool = True
) -> Filter:
    """
    Helper function to create a subscription search filer for two very common
    fields: status and managed.
    """
    return Filter().is_in("status", states).eq("managed", str(managed).lower())


class OCMOrganization(BaseModel):
    """
    Represents an organization in OCM.
    """

    id: str
    name: str

    labels: Optional[list[OCMOrganizationLabel]] = None
    capabilities: Optional[list[OCMCapability]] = None
    """
    Capabilities are a list of features/features flags that are enabled for an organization.
    """


def get_organizations(
    ocm_api: OCMBaseClient, filter: Filter
) -> dict[str, OCMOrganization]:
    """
    Returns a dictionary of organizations based on the provided filter.
    The result is keyed by organization ID.
    """
    organizations = {}
    chunk_size = 100
    for filter_chunk in filter.chunk_by("id", chunk_size, ignore_missing=True):
        for organization_dict in ocm_api.get_paginated(
            api_path="/api/accounts_mgmt/v1/organizations?fetchCapabilities=true&fetchLabels=true",
            params={"search": filter_chunk.render()},
            max_page_size=chunk_size,
        ):
            try:
                org = OCMOrganization(
                    **organization_dict,
                )
                organizations[org.id] = org
            except ValidationError:
                pass
                # ignore subscriptions that fail to validate
                # against the OCMSubscription, since the lack important fields
    return organizations
