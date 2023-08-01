from collections.abc import Callable
from typing import Optional

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.test.ocm.test_utils_ocm_labels import build_subscription_label
from reconcile.utils.ocm.base import (
    OCMCapability,
    OCMSubscription,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.subscriptions import (
    build_subscription_filter,
    get_subscriptions,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_ocm_subscription(
    name: str,
    org_id: str = "org_id",
    cluster_id: Optional[str] = None,
    managed: bool = True,
    status: str = "Active",
    capabilities: Optional[list[tuple[str, str]]] = None,
    labels: Optional[list[tuple[str, str]]] = None,
) -> OCMSubscription:
    id = f"{name}-id"
    return OCMSubscription(
        id=id,
        href=f"http://ocm/sub/{id}",
        display_name=name,
        created_at="2021-09-01T00:00:00Z",
        cluster_id=cluster_id or f"{name}-cluster-id",
        organization_id=org_id,
        status=status,
        managed=managed,
        capabilities=[OCMCapability(name=n, value=v) for n, v in capabilities or []],
        labels=[build_subscription_label(n, v, id) for n, v in labels or []],
    )


def test_get_subscriptions(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    sub = build_ocm_subscription(
        name="sub-1",
        labels=[("label-1", "value-1")],
        capabilities=[("capability-1", "value-1")],
    )
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET", uri="/api/accounts_mgmt/v1/subscriptions"
            ).add_list_response([sub])
        ]
    )
    subscriptions = get_subscriptions(ocm_api, Filter().eq("some", "condition"))
    assert len(subscriptions) == 1
    assert sub.id in subscriptions
    assert sub == subscriptions[sub.id]


def test_build_subscription_filter() -> None:
    filter = build_subscription_filter(states={"Active"})
    assert filter.render() == "managed='true' and status='Active'"


def test_build_subscription_filter_unmanaged() -> None:
    filter = build_subscription_filter(managed=False)
    assert filter.render() == "managed='false'"


def test_build_subscription_filter_multiple_states() -> None:
    filter = build_subscription_filter(states={"Active", "Reserved"})
    assert filter.render() == "managed='true' and status in ('Active','Reserved')"
