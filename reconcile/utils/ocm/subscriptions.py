from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.ocm.labels import OCMSubscriptionLabel
from reconcile.utils.ocm.search_filters import Filter


class OCMCapability(BaseModel):

    name: str
    value: str


class OCMSubscription(BaseModel):

    id: str
    href: str
    display_name: str
    created_at: datetime
    cluster_id: str

    organization_id: str
    managed: bool
    status: str

    labels: Optional[list[OCMSubscriptionLabel]] = None
    capabilities: Optional[list[OCMCapability]] = None


def get_subscriptions(
    ocm_api: OCMBaseClient, filter: Filter
) -> dict[str, OCMSubscription]:
    subscriptions = {}
    chunk_size = 100
    for filter_chunk in filter.chunk_by("id", chunk_size, ignore_missing=True):
        for subscription_dict in ocm_api.get_paginated(
            api_path="/api/accounts_mgmt/v1/subscriptions?fetchCapabilities=true&fetchLabels=true",
            params={"search": filter_chunk.render()},
            max_page_size=chunk_size,
        ):
            subscriptions[subscription_dict["id"]] = OCMSubscription(
                **subscription_dict,
            )
    return subscriptions


def build_subscription_filter(state: str = "Active", managed: bool = True) -> Filter:
    return Filter().eq("status", state).eq("managed", str(managed).lower())
