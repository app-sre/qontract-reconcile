from pydantic import ValidationError

from reconcile.utils.ocm.base import (
    OCMOrganization,
    OCMSubscription,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


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
        # Note, that pagination is currently broken.
        # Each call will return a random order, meaning pages are not consistent.
        # ALWAYS by default use "orderBy: id", as id has an index in the db.
        for subscription_dict in ocm_api.get_paginated(
            api_path="/api/accounts_mgmt/v1/subscriptions?fetchCapabilities=true&fetchLabels=true",
            params={"search": filter_chunk.render(), "orderBy": "id"},
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
    states: set[str] | None = None, managed: bool = True
) -> Filter:
    """
    Helper function to create a subscription search filer for two very common
    fields: status and managed.
    """
    return Filter().is_in("status", states).eq("managed", str(managed).lower())


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
