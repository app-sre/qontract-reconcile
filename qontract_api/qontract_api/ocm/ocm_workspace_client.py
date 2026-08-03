"""OcmWorkspaceClient: caching + composition layer for OCM label-based cluster discovery.

Composes OcmApi.get_labels/get_subscriptions/get_clusters exactly as
reconcile/utils/ocm/clusters.py::discover_clusters_by_labels and
get_cluster_details_for_subscriptions do today, but stays generic over
label_key_prefix (no "rhidp" or other integration-specific knowledge belongs here -
see ADR-013/ADR-014).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, Field
from qontract_utils.ocm_api import (
    ACTIVE_SUBSCRIPTION_STATES,
    Filter,
    OcmIdentityProvider,
    OcmIdentityProviderOidc,
    OcmOrganizationLabel,
    OcmSubscriptionLabel,
    build_subscription_filter,
    cluster_ready_for_app_interface,
    organization_label_filter,
    subscription_label_filter,
)

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from qontract_utils.ocm_api import OcmApi

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)

# Matches the practical limit on OCM `search` IN-clause length used by the legacy
# reconcile/utils/ocm/clusters.py chunk_by("subscription.id", 100, ...).
CLUSTER_FILTER_CHUNK_SIZE = 100


class OcmClusterRecord(BaseModel, frozen=True):
    """One discovered cluster + its merged labels (Layer 2 domain shape)."""

    id: str
    name: str
    organization_id: str
    console_url: str | None
    external_auth_enabled: bool
    labels: dict[str, str] = Field(default_factory=dict)


class CachedOcmClusters(BaseModel, frozen=True):
    """Cached list of OcmClusterRecord for one (environment, label_key_prefix) pair.

    Cached BEFORE org_id filtering, so the same cache entry serves every org_ids
    query against the same OCM environment + label_key_prefix.
    """

    items: list[OcmClusterRecord] = Field(default_factory=list)


class CachedOcmIdentityProviders(BaseModel, frozen=True):
    """Cached list of identity providers for one (environment, cluster_id) pair."""

    items: list[OcmIdentityProvider | OcmIdentityProviderOidc] = Field(
        default_factory=list
    )


class OcmWorkspaceClient:
    """Caching + compute layer for OCM label-based cluster discovery.

    Args:
        ocm_api_factory: Builds an OcmApi on demand. Deferred (not a live instance)
            because OcmApi.__init__ eagerly performs an OAuth2 token exchange with
            Red Hat SSO - a cache hit here must never pay for that.
        cache: Cache backend with two-tier caching (memory + Redis)
        settings: Application settings with OCM config
        environment_key: Stable, non-secret identifier for the OCM environment +
            calling identity (see ocm_client_factory.py), used as a cache-key
            component.

    The underlying OcmApi is built at most once (on first use that isn't a pure
    cache hit) and reused for every subsequent call - reads and mutations alike -
    for this workspace client's lifetime, instead of paying for a fresh OAuth2
    token exchange on every single call. Use as a context manager (or call
    close() explicitly) to release the connection when done. Safe to call from
    multiple threads concurrently (e.g. a thread pool fetching several clusters'
    identity providers at once) - httpx2.Client itself is thread-safe, and the
    lazy build below is guarded so concurrent first-callers can't each build (and
    leak) their own OcmApi.
    """

    def __init__(
        self,
        ocm_api_factory: Callable[[], OcmApi],
        cache: CacheBackend,
        settings: Settings,
        environment_key: str,
    ) -> None:
        self._ocm_api_factory = ocm_api_factory
        self.cache = cache
        self.settings = settings
        self._environment_key = environment_key
        self._ocm_api_instance: OcmApi | None = None
        self._ocm_api_build_lock = threading.Lock()

    @property
    def _ocm_api(self) -> OcmApi:
        """Return a single authenticated OcmApi, reused for this workspace client.

        Built at most once, on first access - avoids a fresh OAuth2 token exchange
        on every call. Double-checked locking so concurrent first-callers block on
        the same build instead of each starting their own OAuth2 exchange.
        """
        if self._ocm_api_instance is None:
            with self._ocm_api_build_lock:
                if self._ocm_api_instance is None:
                    self._ocm_api_instance = self._ocm_api_factory()
        return self._ocm_api_instance

    def close(self) -> None:
        """Close the underlying OcmApi connection, if one was ever built."""
        if self._ocm_api_instance is not None:
            self._ocm_api_instance.close()
            self._ocm_api_instance = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # CACHE KEY HELPERS
    def _cache_key(self, label_key_prefix: str) -> str:
        return f"ocm:clusters:{self._environment_key}:{label_key_prefix}"

    def _idp_cache_key(self, cluster_id: str) -> str:
        return f"ocm:idps:{self._environment_key}:{cluster_id}"

    # CACHE OPERATIONS
    def _get_cached_clusters(self, cache_key: str) -> list[OcmClusterRecord] | None:
        """Get cached clusters.

        Uses `is not None` (not a truthy check) so a genuinely empty result is a
        cache hit, not indistinguishable from a miss - most OCM environments have
        zero clusters matching any given label_key_prefix.
        """
        cached = self.cache.get_obj(cache_key, CachedOcmClusters)
        return cached.items if cached is not None else None

    def _set_cached_clusters(
        self, cache_key: str, items: list[OcmClusterRecord], ttl: int
    ) -> None:
        self.cache.set_obj(cache_key, CachedOcmClusters(items=items), ttl)

    # CACHED DATA ACCESS
    def get_clusters(
        self, label_key_prefix: str, org_ids: set[str] | None = None
    ) -> list[OcmClusterRecord]:
        """Discover clusters whose labels start with label_key_prefix.

        Cached with distributed locking, optionally restricted to org_ids. org_ids
        filtering is applied in Python AFTER the cache lookup, so the cache
        entry is reusable across different org_ids queries against the same
        environment + label_key_prefix.
        """
        cache_key = self._cache_key(label_key_prefix)

        cached = self._get_cached_clusters(cache_key)
        if cached is None:
            with self.cache.lock(cache_key):
                # Double-check after lock
                cached = self._get_cached_clusters(cache_key)
                if cached is None:
                    cached = self._discover_clusters(label_key_prefix)
                    self._set_cached_clusters(
                        cache_key, cached, self.settings.ocm.clusters_cache_ttl
                    )

        if org_ids is None:
            return cached
        return [c for c in cached if c.organization_id in org_ids]

    # DISCOVERY (composition of Layer 1 OcmApi calls)
    def _discover_clusters(self, label_key_prefix: str) -> list[OcmClusterRecord]:
        """Cache-miss path: fetch labels, subscriptions, and clusters from OCM.

        Mirrors reconcile/utils/ocm/clusters.py::discover_clusters_by_labels +
        get_cluster_details_for_subscriptions, generalized over label_key_prefix
        and flattening straight to merged str labels (label interpretation stays
        client-side, so no LabelContainer type is needed here).
        """
        label_filter = subscription_label_filter().like(
            "key", f"{label_key_prefix}%"
        ) | organization_label_filter().like("key", f"{label_key_prefix}%")

        subscription_labels: dict[str, list[OcmSubscriptionLabel]] = defaultdict(list)
        organization_labels: dict[str, list[OcmOrganizationLabel]] = defaultdict(list)
        for label in self._ocm_api.get_labels(label_filter):
            if isinstance(label, OcmSubscriptionLabel):
                subscription_labels[label.subscription_id].append(label)
            else:
                organization_labels[label.organization_id].append(label)

        if not subscription_labels and not organization_labels:
            return []

        subscription_filter = (
            Filter().is_in("id", subscription_labels.keys())
            | Filter().is_in("organization_id", organization_labels.keys())
        ) & build_subscription_filter(states=ACTIVE_SUBSCRIPTION_STATES, managed=True)

        subscriptions = self._ocm_api.get_subscriptions(subscription_filter)
        if not subscriptions:
            return []

        cluster_search_filter = cluster_ready_for_app_interface().is_in(
            "subscription.id", subscriptions.keys()
        )

        records: list[OcmClusterRecord] = []
        for filter_chunk in cluster_search_filter.chunk_by(
            "subscription.id", CLUSTER_FILTER_CHUNK_SIZE, ignore_missing=True
        ):
            for cluster in self._ocm_api.get_clusters(filter_chunk):
                subscription = subscriptions.get(cluster.subscription_id)
                if subscription is None:
                    # Defensive: shouldn't happen given the filter above.
                    logger.warning(
                        "Cluster returned with unknown subscription",
                        cluster_id=cluster.id,
                        subscription_id=cluster.subscription_id,
                    )
                    continue

                merged_labels: dict[str, str] = {}
                for label in organization_labels.get(subscription.organization_id, []):
                    merged_labels[label.key] = label.value
                for label in subscription_labels.get(cluster.subscription_id, []):
                    merged_labels[label.key] = label.value  # subscription wins

                records.append(
                    OcmClusterRecord(
                        id=cluster.id,
                        name=cluster.name,
                        organization_id=subscription.organization_id,
                        console_url=cluster.console_url,
                        external_auth_enabled=cluster.external_auth_enabled,
                        labels=merged_labels,
                    )
                )
        return records

    # IDENTITY PROVIDERS (cached read, invalidating mutations)
    def get_identity_providers(
        self, cluster_id: str
    ) -> list[OcmIdentityProvider | OcmIdentityProviderOidc]:
        """List identity providers configured on a cluster.

        Cached with distributed locking, same double-checked-locking pattern as
        get_clusters - identity providers change rarely relative to how often they're
        read during reconciliation.
        """
        cache_key = self._idp_cache_key(cluster_id)

        cached = self._get_cached_identity_providers(cache_key)
        if cached is None:
            with self.cache.lock(cache_key):
                cached = self._get_cached_identity_providers(cache_key)
                if cached is None:
                    cached = self._ocm_api.get_identity_providers(cluster_id)
                    self.cache.set_obj(
                        cache_key,
                        CachedOcmIdentityProviders(items=cached),
                        self.settings.ocm.identity_providers_cache_ttl,
                    )
        return cached

    def _get_cached_identity_providers(
        self, cache_key: str
    ) -> list[OcmIdentityProvider | OcmIdentityProviderOidc] | None:
        """Get cached identity providers.

        Uses `is not None` (not a truthy check) so a genuinely empty result (a
        cluster with no identity providers configured yet) is a cache hit, not
        indistinguishable from a miss.
        """
        cached = self.cache.get_obj(cache_key, CachedOcmIdentityProviders)
        return cached.items if cached is not None else None

    def create_identity_provider(
        self, cluster_id: str, idp: OcmIdentityProviderOidc
    ) -> OcmIdentityProviderOidc:
        """Create an OIDC identity provider on a cluster, invalidating its IDP cache."""
        created = self._ocm_api.create_identity_provider(cluster_id, idp)
        cache_key = self._idp_cache_key(cluster_id)
        with self.cache.lock(cache_key):
            self.cache.delete(cache_key)
        return created

    def update_identity_provider(
        self, cluster_id: str, idp_id: str, idp: OcmIdentityProviderOidc
    ) -> OcmIdentityProviderOidc:
        """Update an OIDC identity provider on a cluster, invalidating its IDP cache."""
        updated = self._ocm_api.update_identity_provider(cluster_id, idp_id, idp)
        cache_key = self._idp_cache_key(cluster_id)
        with self.cache.lock(cache_key):
            self.cache.delete(cache_key)
        return updated

    def delete_identity_provider(self, cluster_id: str, idp_id: str) -> None:
        """Delete an identity provider from a cluster, invalidating its IDP cache."""
        self._ocm_api.delete_identity_provider(cluster_id, idp_id)
        cache_key = self._idp_cache_key(cluster_id)
        with self.cache.lock(cache_key):
            self.cache.delete(cache_key)
