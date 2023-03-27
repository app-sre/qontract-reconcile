from typing import (
    Any,
    Callable,
    Optional,
)

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.ocm import labels
from reconcile.utils.ocm.labels import (
    OCMAccountLabel,
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
    build_label_from_dict,
    get_organization_labels,
    get_subscription_labels,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_organization_label(key: str, value: str, org_id: str) -> OCMOrganizationLabel:
    return OCMOrganizationLabel(
        created_at="2021-09-01T00:00:00Z",
        updated_at="2021-09-01T00:00:00Z",
        id=f"{key}_id",
        internal=False,
        href=f"https://ocm/label/{key}_id",
        key=key,
        value=value,
        organization_id=org_id,
        type="Organization",
    )


def build_subscription_label(
    key: str, value: str, subs_id: str
) -> OCMSubscriptionLabel:
    return OCMSubscriptionLabel(
        created_at="2021-09-01T00:00:00Z",
        updated_at="2021-09-01T00:00:00Z",
        id=f"{key}_id",
        internal=False,
        href=f"https://ocm/label/{key}_id",
        key=key,
        value=value,
        subscription_id=subs_id,
        type="Subscription",
    )


def test_utils_build_ocm_organization_label_from_dict() -> None:
    key = "some_key"
    value = "some_value"
    organization_id = "some_org_id"
    ocm_label = build_label_from_dict(
        {
            "id": "some_id",
            "internal": False,
            "updated_at": "2021-09-01T00:00:00Z",
            "created_at": "2021-09-01T00:00:00Z",
            "href": "some_href",
            "key": key,
            "value": value,
            "type": "Organization",
            "organization_id": organization_id,
        }
    )
    assert isinstance(ocm_label, OCMOrganizationLabel)
    assert ocm_label.key == key
    assert ocm_label.value == value
    assert ocm_label.organization_id == organization_id


def test_utils_build_ocm_subscription_label_from_dict() -> None:
    key = "some_key"
    value = "some_value"
    subscription_id = "some_sub_id"
    ocm_label = build_label_from_dict(
        {
            "id": "some_id",
            "internal": False,
            "updated_at": "2021-09-01T00:00:00Z",
            "created_at": "2021-09-01T00:00:00Z",
            "href": "some_href",
            "key": key,
            "value": value,
            "type": "Subscription",
            "subscription_id": subscription_id,
        }
    )
    assert isinstance(ocm_label, OCMSubscriptionLabel)
    assert ocm_label.key == key
    assert ocm_label.value == value
    assert ocm_label.subscription_id == subscription_id


def test_utils_build_ocm_account_label_from_dict() -> None:
    key = "some_key"
    value = "some_value"
    account_id = "some_account_id"
    ocm_label = build_label_from_dict(
        {
            "id": "some_id",
            "internal": False,
            "updated_at": "2021-09-01T00:00:00Z",
            "created_at": "2021-09-01T00:00:00Z",
            "href": "some_href",
            "key": key,
            "value": value,
            "type": "Account",
            "account_id": account_id,
        }
    )
    assert isinstance(ocm_label, OCMAccountLabel)
    assert ocm_label.key == key
    assert ocm_label.value == value
    assert ocm_label.account_id == account_id


def test_utils_build_ocm_unknown_label_from_dict() -> None:
    with pytest.raises(ValueError):
        build_label_from_dict(
            {
                "type": "Unknown",
            }
        )


def test_utils_get_organization_labels(
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    register_ocm_get_list_handler: Callable[[str, Optional[Any]], None],
) -> None:
    get_labels_call_recorder = mocker.patch.object(
        labels, "get_labels", wraps=labels.get_labels
    )
    register_ocm_get_list_handler(
        "/api/accounts_mgmt/v1/labels",
        [
            build_organization_label("label", "value", "org_id").dict(by_alias=True),
        ],
    )

    filter = Filter().eq("additional", "filter")
    org_labels = list(
        get_organization_labels(
            ocm_api=ocm_api,
            filter=filter,
        )
    )

    # make sure we got the label we expected
    assert len(org_labels) == 1
    assert isinstance(org_labels[0], OCMOrganizationLabel)
    assert org_labels[0].key == "label"

    # make sure the filter was applied correctly
    get_labels_call_recorder.assert_called_once_with(
        ocm_api=ocm_api, filter=filter.eq("type", "Organization")
    )


def test_utils_get_subscription_labels(
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    register_ocm_get_list_handler: Callable[[str, Optional[Any]], None],
) -> None:
    get_labels_call_recorder = mocker.patch.object(
        labels, "get_labels", wraps=labels.get_labels
    )
    register_ocm_get_list_handler(
        "/api/accounts_mgmt/v1/labels",
        [
            build_subscription_label("label", "value", "sub_id").dict(by_alias=True),
        ],
    )

    filter = Filter().eq("additional", "filter")
    org_labels = list(
        get_subscription_labels(
            ocm_api=ocm_api,
            filter=filter,
        )
    )

    # make sure we got the label we expected
    assert len(org_labels) == 1
    assert isinstance(org_labels[0], OCMSubscriptionLabel)
    assert org_labels[0].key == "label"

    # make sure the filter was applied correctly
    get_labels_call_recorder.assert_called_once_with(
        ocm_api=ocm_api, filter=filter.eq("type", "Subscription")
    )


def test_build_label_filter_for_key() -> None:
    filter = labels.label_filter("foo")
    assert filter == Filter().eq("key", "foo")


def test_build_label_filter_for_key_and_value() -> None:
    filter = labels.label_filter("foo", "bar")
    assert filter == Filter().eq("key", "foo").eq("value", "bar")
