from typing import Optional

import httpretty as httpretty_module

from reconcile.test.ocm.conftest import register_ocm_get_list_request
from reconcile.test.ocm.test_utils_ocm_labels import build_subscription_label
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.subscriptions import (
    OCMCapability,
    OCMSubscription,
    build_subscription_filter,
    get_subscriptions,
)


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


def test_get_subscriptions(ocm_api: OCMBaseClient, httpretty: httpretty_module):
    sub = build_ocm_subscription(
        name="sub-1",
        labels=[("label-1", "value-1")],
        capabilities=[("capability-1", "value-1")],
    )
    register_ocm_get_list_request(
        ocm_api,
        httpretty,
        "/api/accounts_mgmt/v1/subscriptions",
        [sub],
    )
    subscriptions = get_subscriptions(ocm_api, Filter().eq("some", "condition"))
    assert len(subscriptions) == 1
    assert sub.id in subscriptions
    assert sub == subscriptions[sub.id]


def test_build_subscription_filter():
    filter = build_subscription_filter()
    assert filter.render() == "managed='true' and status='Active'"


def test_build_subscription_filter_unmanaged():
    filter = build_subscription_filter(managed=False)
    assert filter.render() == "managed='false' and status='Active'"


def test_build_subscription_filter_state():
    filter = build_subscription_filter(state="Stale")
    assert filter.render() == "managed='true' and status='Stale'"
