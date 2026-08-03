"""Tests for OcmWorkspaceClient caching + composition layer."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.ocm_api import OcmApi
from qontract_utils.ocm_api.models import (
    OcmCluster,
    OcmOrganizationLabel,
    OcmSubscription,
    OcmSubscriptionLabel,
)

from qontract_api.cache.base import CacheBackend
from qontract_api.config import OcmSettings, Settings
from qontract_api.external.ocm.ocm_workspace_client import (
    CachedOcmClusters,
    OcmClusterRecord,
    OcmWorkspaceClient,
)


@pytest.fixture
def mock_ocm_api() -> MagicMock:
    """Create mock OcmApi."""
    return MagicMock(spec=OcmApi)


@pytest.fixture
def mock_ocm_api_factory(mock_ocm_api: MagicMock) -> MagicMock:
    """Create mock factory closure returning mock_ocm_api."""
    return MagicMock(return_value=mock_ocm_api)


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock CacheBackend."""
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(ocm=OcmSettings(clusters_cache_ttl=300))


@pytest.fixture
def client(
    mock_ocm_api_factory: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> OcmWorkspaceClient:
    """Create OcmWorkspaceClient with mocked dependencies."""
    return OcmWorkspaceClient(
        ocm_api_factory=mock_ocm_api_factory,
        cache=mock_cache,
        settings=settings,
        environment_key="env-abc123",
    )


def test_cache_key_format(client: OcmWorkspaceClient) -> None:
    """Test cache key format."""
    cache_key = client._cache_key("sre-capabilities.rhidp")
    assert cache_key == "ocm:clusters:env-abc123:sre-capabilities.rhidp"


def test_get_clusters_cache_hit_returns_without_calling_factory(
    client: OcmWorkspaceClient,
    mock_cache: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    """Test get_clusters returns cached data on cache hit without building OcmApi."""
    record = OcmClusterRecord(
        id="cluster-1",
        name="my-cluster",
        organization_id="org-1",
        console_url="https://console.example.com",
        external_auth_enabled=False,
        labels={"sre-capabilities.rhidp.name": "rhidp1"},
    )
    mock_cache.get_obj.return_value = CachedOcmClusters(items=[record])

    result = client.get_clusters("sre-capabilities.rhidp")

    assert result == [record]
    mock_ocm_api_factory.assert_not_called()


def test_get_clusters_cache_hit_empty_list_is_respected(
    client: OcmWorkspaceClient,
    mock_cache: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    """A genuinely empty cached result must be treated as a hit, not a miss.

    This is the regression test for the pagerduty-style truthy-check bug: if
    get_clusters used `if cached:` instead of `is not None`, an empty cached list
    would look like a miss and re-trigger discovery (and the OAuth2 token
    exchange) on every single call.
    """
    mock_cache.get_obj.return_value = CachedOcmClusters(items=[])

    result = client.get_clusters("sre-capabilities.rhidp")

    assert result == []
    mock_ocm_api_factory.assert_not_called()
    mock_cache.lock.assert_not_called()


def test_get_clusters_cache_miss_discovers_labels_subscriptions_clusters(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test cache-miss path composes labels, subscriptions, and clusters correctly."""
    mock_ocm_api.get_labels.return_value = [
        OcmSubscriptionLabel(
            key="sre-capabilities.rhidp.name", value="rhidp1", subscription_id="sub-1"
        ),
    ]
    mock_ocm_api.get_subscriptions.return_value = {
        "sub-1": OcmSubscription(
            id="sub-1", organization_id="org-1", status="Active", managed=True
        )
    }
    mock_ocm_api.get_clusters.return_value = [
        OcmCluster(
            id="cluster-1",
            name="my-cluster",
            subscription_id="sub-1",
            console_url="https://console.example.com",
            external_auth_enabled=False,
        )
    ]

    result = client.get_clusters("sre-capabilities.rhidp")

    assert len(result) == 1
    record = result[0]
    assert record.id == "cluster-1"
    assert record.organization_id == "org-1"  # comes from subscription, not label
    assert record.labels == {"sre-capabilities.rhidp.name": "rhidp1"}

    mock_cache.set_obj.assert_called_once()
    call_args = mock_cache.set_obj.call_args
    assert call_args[0][1] == CachedOcmClusters(items=result)
    assert call_args[0][2] == settings.ocm.clusters_cache_ttl


def test_get_clusters_label_merge_precedence(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    """Test subscription-level labels win over organization-level labels."""
    mock_ocm_api.get_labels.return_value = [
        OcmOrganizationLabel(
            key="sre-capabilities.rhidp.status",
            value="org-value",
            organization_id="org-1",
        ),
        OcmSubscriptionLabel(
            key="sre-capabilities.rhidp.status",
            value="sub-value",
            subscription_id="sub-1",
        ),
    ]
    mock_ocm_api.get_subscriptions.return_value = {
        "sub-1": OcmSubscription(
            id="sub-1", organization_id="org-1", status="Active", managed=True
        )
    }
    mock_ocm_api.get_clusters.return_value = [
        OcmCluster(
            id="cluster-1",
            name="my-cluster",
            subscription_id="sub-1",
            console_url=None,
            external_auth_enabled=False,
        )
    ]

    result = client.get_clusters("sre-capabilities.rhidp")

    assert result[0].labels == {"sre-capabilities.rhidp.status": "sub-value"}


def test_get_clusters_no_matching_labels_caches_empty_result(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test that no matching labels returns and caches an empty list."""
    mock_ocm_api.get_labels.return_value = []

    result = client.get_clusters("sre-capabilities.rhidp")

    assert result == []
    mock_ocm_api.get_subscriptions.assert_not_called()
    mock_cache.set_obj.assert_called_once()
    call_args = mock_cache.set_obj.call_args
    assert call_args[0][1] == CachedOcmClusters(items=[])


def test_get_clusters_no_matching_subscriptions_after_active_managed_filter(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test that labels found but no active/managed subscriptions returns empty."""
    mock_ocm_api.get_labels.return_value = [
        OcmSubscriptionLabel(
            key="sre-capabilities.rhidp.name", value="rhidp1", subscription_id="sub-1"
        ),
    ]
    mock_ocm_api.get_subscriptions.return_value = {}

    result = client.get_clusters("sre-capabilities.rhidp")

    assert result == []
    mock_ocm_api.get_clusters.assert_not_called()
    mock_cache.set_obj.assert_called_once()


def test_get_clusters_filters_by_org_ids_after_cache_hit(
    client: OcmWorkspaceClient,
    mock_cache: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    """Test org_ids filtering happens in Python after a cache hit."""
    record_org1 = OcmClusterRecord(
        id="cluster-1",
        name="cluster-1",
        organization_id="org-1",
        console_url=None,
        external_auth_enabled=False,
    )
    record_org2 = OcmClusterRecord(
        id="cluster-2",
        name="cluster-2",
        organization_id="org-2",
        console_url=None,
        external_auth_enabled=False,
    )
    mock_cache.get_obj.return_value = CachedOcmClusters(
        items=[record_org1, record_org2]
    )

    result = client.get_clusters("sre-capabilities.rhidp", org_ids={"org-1"})

    assert result == [record_org1]
    mock_ocm_api_factory.assert_not_called()


def test_get_clusters_org_ids_none_returns_all_cached(
    client: OcmWorkspaceClient, mock_cache: MagicMock
) -> None:
    """Test org_ids=None returns all cached clusters unfiltered."""
    record_org1 = OcmClusterRecord(
        id="cluster-1",
        name="cluster-1",
        organization_id="org-1",
        console_url=None,
        external_auth_enabled=False,
    )
    record_org2 = OcmClusterRecord(
        id="cluster-2",
        name="cluster-2",
        organization_id="org-2",
        console_url=None,
        external_auth_enabled=False,
    )
    mock_cache.get_obj.return_value = CachedOcmClusters(
        items=[record_org1, record_org2]
    )

    result = client.get_clusters("sre-capabilities.rhidp", org_ids=None)

    assert result == [record_org1, record_org2]


def test_get_clusters_acquires_lock_on_cache_miss(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_clusters acquires distributed lock on cache miss."""
    mock_ocm_api.get_labels.return_value = []

    client.get_clusters("sre-capabilities.rhidp")

    mock_cache.lock.assert_called_once_with(
        "ocm:clusters:env-abc123:sre-capabilities.rhidp"
    )


def test_get_clusters_double_check_after_lock(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_ocm_api_factory: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_clusters double-checks cache after acquiring lock."""
    record = OcmClusterRecord(
        id="cluster-1",
        name="cluster-1",
        organization_id="org-1",
        console_url=None,
        external_auth_enabled=False,
    )
    mock_cache.get_obj.side_effect = [None, CachedOcmClusters(items=[record])]

    result = client.get_clusters("sre-capabilities.rhidp")

    assert result == [record]
    mock_ocm_api_factory.assert_not_called()
    mock_ocm_api.get_labels.assert_not_called()


def test_discover_clusters_closes_ocm_api_after_use(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    """Test that OcmApi.close() is called after a cache-miss discovery."""
    mock_ocm_api.get_labels.return_value = []

    client.get_clusters("sre-capabilities.rhidp")

    mock_ocm_api.close.assert_called_once()


def test_discover_clusters_closes_ocm_api_even_on_error(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    """Test that OcmApi.close() is called even when discovery raises."""
    mock_ocm_api.get_labels.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        client.get_clusters("sre-capabilities.rhidp")

    mock_ocm_api.close.assert_called_once()


def test_discover_clusters_ignores_cluster_with_unknown_subscription(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    """Test a cluster whose subscription_id is missing from subscriptions is skipped."""
    mock_ocm_api.get_labels.return_value = [
        OcmSubscriptionLabel(
            key="sre-capabilities.rhidp.name", value="rhidp1", subscription_id="sub-1"
        ),
    ]
    mock_ocm_api.get_subscriptions.return_value = {
        "sub-1": OcmSubscription(
            id="sub-1", organization_id="org-1", status="Active", managed=True
        )
    }
    mock_ocm_api.get_clusters.return_value = [
        OcmCluster(
            id="cluster-unknown",
            name="cluster-unknown",
            subscription_id="sub-unknown",
            console_url=None,
            external_auth_enabled=False,
        )
    ]

    result = client.get_clusters("sre-capabilities.rhidp")

    assert result == []
