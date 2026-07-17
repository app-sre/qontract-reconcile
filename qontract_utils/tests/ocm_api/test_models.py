"""Tests for qontract_utils.ocm_api.models."""

from qontract_utils.ocm_api.models import (
    OcmCluster,
    OcmOrganizationLabel,
    OcmSubscription,
    OcmSubscriptionLabel,
)


def test_ocm_subscription_label_fields() -> None:
    label = OcmSubscriptionLabel(key="k", value="v", subscription_id="sub-1")
    assert label.key == "k"
    assert label.value == "v"
    assert label.subscription_id == "sub-1"


def test_ocm_organization_label_fields() -> None:
    label = OcmOrganizationLabel(key="k", value="v", organization_id="org-1")
    assert label.key == "k"
    assert label.value == "v"
    assert label.organization_id == "org-1"


def test_ocm_subscription_roundtrip() -> None:
    subscription = OcmSubscription(
        id="sub-1", organization_id="org-1", status="Active", managed=True
    )
    assert subscription.id == "sub-1"
    assert subscription.organization_id == "org-1"
    assert subscription.status == "Active"
    assert subscription.managed is True


def test_ocm_cluster_console_url_optional() -> None:
    cluster = OcmCluster(
        id="cluster-1",
        name="my-cluster",
        subscription_id="sub-1",
        console_url=None,
        external_auth_enabled=False,
    )
    assert cluster.console_url is None


def test_ocm_cluster_with_console_url() -> None:
    cluster = OcmCluster(
        id="cluster-1",
        name="my-cluster",
        subscription_id="sub-1",
        console_url="https://console.example.com",
        external_auth_enabled=True,
    )
    assert cluster.console_url == "https://console.example.com"
    assert cluster.external_auth_enabled is True
