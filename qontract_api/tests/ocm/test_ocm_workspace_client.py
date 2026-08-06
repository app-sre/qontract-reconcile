"""Tests for OcmWorkspaceClient caching + composition layer."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from qontract_utils.ocm_api import OcmApi
from qontract_utils.ocm_api.models import (
    OcmCluster,
    OcmIdentityProvider,
    OcmIdentityProviderOidc,
    OcmIdentityProviderOidcOpenId,
    OcmOrganizationLabel,
    OcmSubscription,
    OcmSubscriptionLabel,
)

from qontract_api.cache.base import CacheBackend
from qontract_api.config import OcmSettings, Settings
from qontract_api.ocm.ocm_workspace_client import (
    CachedOcmClusters,
    CachedOcmIdentityProviders,
    OcmClusterRecord,
    OcmWorkspaceClient,
)


@pytest.fixture
def mock_ocm_api() -> MagicMock:
    """Create mock OcmApi, with __enter__ returning self like the real client."""
    mock = MagicMock(spec=OcmApi)
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


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


def test_discover_clusters_does_not_close_ocm_api_after_use(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    """The OcmApi is reused for this workspace client's lifetime - a single

    cache-miss discovery must not close it, otherwise a later call (e.g. an
    identity-provider fetch) would fail against a closed connection.
    """
    mock_ocm_api.get_labels.return_value = []

    client.get_clusters("sre-capabilities.rhidp")

    mock_ocm_api.__exit__.assert_not_called()
    mock_ocm_api.close.assert_not_called()


def test_discover_clusters_does_not_close_ocm_api_on_error(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    mock_ocm_api.get_labels.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        client.get_clusters("sre-capabilities.rhidp")

    mock_ocm_api.close.assert_not_called()


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


#
# identity providers
#


def _oidc_idp(idp_id: str = "idp-1") -> OcmIdentityProviderOidc:
    return OcmIdentityProviderOidc(
        name="redhat-sso",
        id=idp_id,
        open_id=OcmIdentityProviderOidcOpenId(
            client_id="client-1", issuer="https://issuer.example.com"
        ),
    )


def test_idp_cache_key_format(client: OcmWorkspaceClient) -> None:
    cache_key = client._idp_cache_key("cluster-1")
    assert cache_key == "ocm:idps:env-abc123:cluster-1"


def test_get_identity_providers_cache_hit_returns_without_calling_factory(
    client: OcmWorkspaceClient,
    mock_cache: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    idp = _oidc_idp()
    mock_cache.get_obj.return_value = CachedOcmIdentityProviders(items=[idp])

    result = client.get_identity_providers("cluster-1")

    assert result == [idp]
    mock_ocm_api_factory.assert_not_called()


def test_get_identity_providers_cache_hit_empty_list_is_respected(
    client: OcmWorkspaceClient,
    mock_cache: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    """A genuinely empty cached result (no IDPs on the cluster yet) must be a hit."""
    mock_cache.get_obj.return_value = CachedOcmIdentityProviders(items=[])

    result = client.get_identity_providers("cluster-1")

    assert result == []
    mock_ocm_api_factory.assert_not_called()
    mock_cache.lock.assert_not_called()


def test_get_identity_providers_cache_miss_fetches_and_caches(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    idp = _oidc_idp()
    mock_ocm_api.get_identity_providers.return_value = [idp]

    result = client.get_identity_providers("cluster-1")

    assert result == [idp]
    mock_ocm_api.get_identity_providers.assert_called_once_with("cluster-1")
    mock_cache.set_obj.assert_called_once_with(
        "ocm:idps:env-abc123:cluster-1",
        CachedOcmIdentityProviders(items=[idp]),
        settings.ocm.identity_providers_cache_ttl,
    )


def test_get_identity_providers_acquires_lock_on_cache_miss(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_ocm_api.get_identity_providers.return_value = []

    client.get_identity_providers("cluster-1")

    mock_cache.lock.assert_called_once_with("ocm:idps:env-abc123:cluster-1")


def test_get_identity_providers_double_check_after_lock(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_ocm_api_factory: MagicMock,
    mock_cache: MagicMock,
) -> None:
    idp = _oidc_idp()
    mock_cache.get_obj.side_effect = [None, CachedOcmIdentityProviders(items=[idp])]

    result = client.get_identity_providers("cluster-1")

    assert result == [idp]
    mock_ocm_api_factory.assert_not_called()
    mock_ocm_api.get_identity_providers.assert_not_called()


def test_get_identity_providers_does_not_close_ocm_api_after_use(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    mock_ocm_api.get_identity_providers.return_value = []

    client.get_identity_providers("cluster-1")

    mock_ocm_api.close.assert_not_called()


def test_ocm_api_is_built_lazily_and_reused_across_calls(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    """The whole point of the fix: reads and mutations share ONE authenticated

    OcmApi for this workspace client's lifetime, instead of a fresh OAuth2 token
    exchange on every single call.
    """
    mock_ocm_api.get_labels.return_value = []
    mock_ocm_api.get_identity_providers.return_value = []
    mock_ocm_api_factory.assert_not_called()

    client.get_clusters("sre-capabilities.rhidp")
    client.get_identity_providers("cluster-1")
    client.get_identity_providers("cluster-2")

    mock_ocm_api_factory.assert_called_once()


def test_ocm_api_lazy_build_is_thread_safe(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    """Concurrent first-callers (e.g. a thread pool fetching several clusters'

    identity providers at once) must block on the same OcmApi build instead of each
    racing to build (and leak) their own. Uses a barrier to maximize the chance of
    triggering the race if the double-checked locking were missing or broken.
    """
    mock_ocm_api.get_identity_providers.return_value = []
    thread_count = 16
    barrier = threading.Barrier(thread_count)

    def _fetch(cluster_id: str) -> None:
        barrier.wait(timeout=5)
        client.get_identity_providers(cluster_id)

    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(_fetch, f"cluster-{i}") for i in range(thread_count)]
        for future in futures:
            future.result(timeout=5)

    mock_ocm_api_factory.assert_called_once()


def test_close_closes_ocm_api_if_built(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    client.get_identity_providers("cluster-1")

    client.close()

    mock_ocm_api.close.assert_called_once()


def test_close_is_noop_if_ocm_api_never_built(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_ocm_api_factory: MagicMock,
) -> None:
    """A pure cache hit never builds an OcmApi - closing must not build one either."""
    client.close()

    mock_ocm_api_factory.assert_not_called()
    mock_ocm_api.close.assert_not_called()


def test_context_manager_closes_ocm_api(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    with client:
        client.get_identity_providers("cluster-1")

    mock_ocm_api.close.assert_called_once()


def test_get_identity_providers_classifies_foreign_types(
    client: OcmWorkspaceClient, mock_ocm_api: MagicMock
) -> None:
    github_idp = OcmIdentityProvider(type="GithubIdentityProvider", name="github")
    mock_ocm_api.get_identity_providers.return_value = [github_idp]

    result = client.get_identity_providers("cluster-1")

    assert result == [github_idp]


def test_create_identity_provider_invalidates_cache(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_ocm_api_factory: MagicMock,
    mock_cache: MagicMock,
) -> None:
    idp = _oidc_idp()
    mock_ocm_api.create_identity_provider.return_value = idp

    result = client.create_identity_provider("cluster-1", idp)

    assert result == idp
    mock_ocm_api.create_identity_provider.assert_called_once_with("cluster-1", idp)
    mock_cache.delete.assert_called_once_with("ocm:idps:env-abc123:cluster-1")
    mock_ocm_api_factory.assert_called_once()


def test_create_identity_provider_invalidation_holds_lock(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Cache invalidation must hold the same lock get_identity_providers fills under.

    Otherwise a concurrent reader's fill can race the invalidation and overwrite it
    with stale data right after this delete runs - see
    qontract_api/secret_manager/_base.py for the same established pattern.
    """
    idp = _oidc_idp()
    mock_ocm_api.create_identity_provider.return_value = idp

    client.create_identity_provider("cluster-1", idp)

    mock_cache.lock.assert_called_once_with("ocm:idps:env-abc123:cluster-1")
    mock_cache.delete.assert_called_once_with("ocm:idps:env-abc123:cluster-1")


def test_update_identity_provider_invalidates_cache(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    idp = _oidc_idp()
    mock_ocm_api.update_identity_provider.return_value = idp

    result = client.update_identity_provider("cluster-1", "idp-1", idp)

    assert result == idp
    mock_ocm_api.update_identity_provider.assert_called_once_with(
        "cluster-1", "idp-1", idp
    )
    mock_cache.lock.assert_called_once_with("ocm:idps:env-abc123:cluster-1")
    mock_cache.delete.assert_called_once_with("ocm:idps:env-abc123:cluster-1")


def test_delete_identity_provider_invalidates_cache(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.delete_identity_provider("cluster-1", "idp-1")

    mock_ocm_api.delete_identity_provider.assert_called_once_with("cluster-1", "idp-1")
    mock_cache.lock.assert_called_once_with("ocm:idps:env-abc123:cluster-1")
    mock_cache.delete.assert_called_once_with("ocm:idps:env-abc123:cluster-1")


def test_create_identity_provider_closes_ocm_api_even_on_error(
    client: OcmWorkspaceClient,
    mock_ocm_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Cache must not be invalidated if the OCM API call itself failed."""
    mock_ocm_api.create_identity_provider.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        client.create_identity_provider("cluster-1", _oidc_idp())

    mock_cache.delete.assert_not_called()
