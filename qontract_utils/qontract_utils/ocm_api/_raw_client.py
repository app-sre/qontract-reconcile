"""Wire-format models and a thin httpx2-based raw client for the OCM API.

Models are scoped to only the fields actually read by qontract_utils.ocm_api.client - not
a full mirror of OCM's schema. See qontract_utils.ocm_api.models for the domain models
these are mapped into.

RawOcmClient owns the URLs/paths, pagination, and JSON<->pydantic (de)serialization for
each operation - callers get back the full (already paginated) list of raw items. It has
no business logic, no hooks, no retries - it's handed an already authenticated/configured
httpx2.Client by qontract_utils.ocm_api.client.OcmApi, which owns that client's lifecycle
(construction, close()).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal

import httpx2
from pydantic import BaseModel, Field

MAX_PAGE_SIZE = 100


class RawSubscriptionLabel(BaseModel):
    type: Literal["Subscription"]
    id: str
    key: str
    value: str
    subscription_id: str


class RawOrganizationLabel(BaseModel):
    type: Literal["Organization"]
    id: str
    key: str
    value: str
    organization_id: str


RawLabel = Annotated[
    RawSubscriptionLabel | RawOrganizationLabel, Field(discriminator="type")
]


class RawLabelList(BaseModel):
    items: list[RawLabel] = Field(default_factory=list)
    page: int = 1
    size: int = 0
    total: int = 0


class RawSubscription(BaseModel):
    id: str
    organization_id: str
    status: str
    managed: bool


class RawSubscriptionList(BaseModel):
    items: list[RawSubscription] = Field(default_factory=list)
    page: int = 1
    size: int = 0
    total: int = 0


class RawClusterSubscription(BaseModel):
    id: str


class RawClusterConsole(BaseModel):
    url: str


class RawClusterExternalAuthConfig(BaseModel):
    enabled: bool


class RawCluster(BaseModel):
    id: str
    name: str
    subscription: RawClusterSubscription
    console: RawClusterConsole | None = None
    external_auth_config: RawClusterExternalAuthConfig | None = None


class RawClusterList(BaseModel):
    items: list[RawCluster] = Field(default_factory=list)
    page: int = 1
    size: int = 0
    total: int = 0


class RawOcmClient:
    """Thin httpx2-based OCM client - request building, pagination, and pydantic (de)serialization only."""

    def __init__(self, client: httpx2.Client) -> None:
        self._client = client

    @staticmethod
    def _fetch_all_pages[T](
        fetch_page: Callable[[int], tuple[list[T], int]],
    ) -> list[T]:
        """Fetch all pages from a paginated OCM endpoint.

        Args:
            fetch_page: given a page number, returns (items_on_page, records_on_page)

        Note: pagination ordering is unreliable unless the request is sorted by a
        field with a db index (e.g. "id" or "created_at") - see callers.
        """
        items: list[T] = []
        page = 1
        while True:
            page_items, records_on_page = fetch_page(page)
            items.extend(page_items)
            if records_on_page < MAX_PAGE_SIZE:
                return items
            page += 1

    def get_labels(
        self, *, search: str, order_by: Literal["created_at"]
    ) -> list[RawLabel]:
        def fetch_page(page: int) -> tuple[list[RawLabel], int]:
            response = self._client.get(
                "/api/accounts_mgmt/v1/labels",
                params={
                    "search": search,
                    "orderBy": order_by,
                    "page": page,
                    "size": MAX_PAGE_SIZE,
                },
            )
            response.raise_for_status()
            raw_list = RawLabelList.model_validate(response.json())
            return raw_list.items, raw_list.size

        return self._fetch_all_pages(fetch_page)

    def get_subscriptions(
        self,
        *,
        search: str,
        order_by: Literal["id"],
        fetch_labels: bool,
        fetch_capabilities: bool,
    ) -> list[RawSubscription]:
        def fetch_page(page: int) -> tuple[list[RawSubscription], int]:
            response = self._client.get(
                "/api/accounts_mgmt/v1/subscriptions",
                params={
                    "search": search,
                    "orderBy": order_by,
                    "page": page,
                    "size": MAX_PAGE_SIZE,
                    "fetchLabels": fetch_labels,
                    "fetchCapabilities": fetch_capabilities,
                },
            )
            response.raise_for_status()
            raw_list = RawSubscriptionList.model_validate(response.json())
            return raw_list.items, raw_list.size

        return self._fetch_all_pages(fetch_page)

    def get_clusters(
        self, *, search: str, order: Literal["creation_timestamp"]
    ) -> list[RawCluster]:
        def fetch_page(page: int) -> tuple[list[RawCluster], int]:
            response = self._client.get(
                "/api/clusters_mgmt/v1/clusters",
                params={
                    "search": search,
                    "order": order,
                    "page": page,
                    "size": MAX_PAGE_SIZE,
                },
            )
            response.raise_for_status()
            raw_list = RawClusterList.model_validate(response.json())
            return raw_list.items, raw_list.size

        return self._fetch_all_pages(fetch_page)
