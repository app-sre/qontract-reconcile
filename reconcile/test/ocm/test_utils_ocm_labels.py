from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm import labels
from reconcile.utils.ocm.labels import (
    LabelContainer,
    OCMAccountLabel,
    OCMOrganizationLabel,
    OCMSubscriptionLabel,
    build_container_for_prefix,
    build_label_container,
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
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    get_labels_call_recorder = mocker.patch.object(
        labels, "get_labels", wraps=labels.get_labels
    )
    register_ocm_url_responses(
        [
            OcmUrl(method="GET", uri="/api/accounts_mgmt/v1/labels").add_list_response(
                [
                    build_organization_label("label", "value", "org_id").dict(
                        by_alias=True
                    )
                ]
            )
        ]
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
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    get_labels_call_recorder = mocker.patch.object(
        labels, "get_labels", wraps=labels.get_labels
    )
    register_ocm_url_responses(
        [
            OcmUrl(method="GET", uri="/api/accounts_mgmt/v1/labels").add_list_response(
                [
                    build_subscription_label("label", "value", "sub_id").dict(
                        by_alias=True
                    )
                ]
            )
        ]
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


#
# LabelContainer tests
#


def test_build_label_container_list_override() -> None:
    list_a = [
        build_organization_label(key="1", value="a", org_id="org_id"),
        build_organization_label(key="2", value="a", org_id="org_id"),
    ]
    list_b = [
        build_organization_label(key="2", value="b", org_id="org_id"),
        build_organization_label(key="3", value="b", org_id="org_id"),
    ]
    lc = build_label_container(list_a, list_b)

    assert len(lc) == 3
    assert lc.get_label_value("1") == "a"
    assert lc.get_label_value("2") == "b"  # overwritten by list_b
    assert lc.get_label_value("3") == "b"


def test_build_label_container_empty() -> None:
    assert len(build_label_container()) == 0
    assert len(build_label_container([])) == 0
    assert len(build_label_container(None)) == 0


@pytest.fixture
def label_container() -> LabelContainer:
    return build_label_container(
        [
            build_organization_label(key="a.a", value="a", org_id="org_id"),
            build_organization_label(key="a.b", value="b", org_id="org_id"),
            build_organization_label(key="a.c", value="c", org_id="org_id"),
            build_organization_label(key="another_label", value="v", org_id="org_id"),
        ]
    )


def test_label_container_get_label(label_container: LabelContainer) -> None:
    existing_label = label_container.get("a.a")
    assert existing_label
    assert existing_label.key == "a.a"

    missing_label = label_container.get("missing")
    assert missing_label is None


def test_label_container_get_required_label(label_container: LabelContainer) -> None:
    existing_label = label_container.get_required_label("a.a")
    assert existing_label.key == "a.a"

    with pytest.raises(ValueError):
        label_container.get_required_label("missing")


def test_label_container_get_label_value(label_container: LabelContainer) -> None:
    assert label_container.get_label_value("a.a") == "a"
    assert label_container.get_label_value("missing") is None


def test_label_container_get_values_dict(label_container: LabelContainer) -> None:
    assert label_container.get_values_dict() == {
        "a.a": "a",
        "a.b": "b",
        "a.c": "c",
        "another_label": "v",
    }


def test_build_label_container_for_prefix(label_container: LabelContainer) -> None:
    sub_container = build_container_for_prefix(label_container, "a.")
    assert len(sub_container) == 3
    label_a_a = sub_container.get("a.a")
    assert label_a_a
    assert label_a_a.key == "a.a"
    assert sub_container.get_values_dict() == {"a.a": "a", "a.b": "b", "a.c": "c"}


def test_build_label_container_for_prefix_strip_prefix(
    label_container: LabelContainer,
) -> None:
    sub_container = build_container_for_prefix(
        label_container, "a.", strip_key_prefix=True
    )
    assert len(sub_container) == 3
    label_a = sub_container.get("a")
    assert label_a
    assert label_a.key == "a"
    assert sub_container.get_values_dict() == {"a": "a", "b": "b", "c": "c"}
