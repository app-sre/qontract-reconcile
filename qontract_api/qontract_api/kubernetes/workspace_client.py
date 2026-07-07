"""Kubernetes workspace client with cached operations.

Layer 2 (Cache + Compute) following ADR-014. Wraps the Layer 1
KubernetesApi with distributed caching for namespace operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_utils.kubernetes import KubernetesApi, Namespace

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedNamespaceNames(BaseModel, frozen=True):
    """Cached set of all namespace names on a cluster."""

    names: frozenset[str]


class KubernetesWorkspaceClient:
    """Caching layer for Kubernetes namespace operations.

    Caches the full set of namespace names per cluster (single LIST call)
    instead of checking each namespace individually.
    Mutations (create/delete) invalidate the cached set.
    """

    def __init__(
        self,
        kubernetes_api: KubernetesApi,
        cluster_name: str,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        self._api = kubernetes_api
        self._cluster_name = cluster_name
        self._cache = cache
        self._settings = settings

    def _cache_key_namespace_names(self) -> str:
        return f"kubernetes:{self._cluster_name}:namespace_names"

    def _get_namespace_names(self) -> frozenset[str]:
        """Get the cached set of namespace names, or fetch and cache it."""
        cache_key = self._cache_key_namespace_names()

        if cached := self._cache.get_obj(cache_key, CachedNamespaceNames):
            return cached.names

        with self._cache.lock(cache_key):
            if cached := self._cache.get_obj(cache_key, CachedNamespaceNames):
                return cached.names

            namespaces = self._api.list_namespaces()
            names = frozenset(
                ns.metadata.name
                for ns in namespaces
                if ns.metadata and ns.metadata.name
            )
            self._cache.set_obj(
                cache_key,
                CachedNamespaceNames(names=names),
                self._settings.kubernetes.namespace_cache_ttl,
            )
            return names

    def _invalidate_namespace_cache(self) -> None:
        self._cache.delete(self._cache_key_namespace_names())

    def namespace_exists(self, name: str) -> bool:
        """Check if a namespace exists (cached via full namespace listing)."""
        return name in self._get_namespace_names()

    def create_namespace(self, name: str) -> Namespace:
        """Create a namespace and invalidate cache."""
        result = self._api.create_namespace(name)
        self._invalidate_namespace_cache()
        return result

    def delete_namespace(self, name: str) -> None:
        """Delete a namespace and invalidate cache."""
        self._api.delete_namespace(name)
        self._invalidate_namespace_cache()

    def list_namespaces(self) -> list[Namespace]:
        """List all namespaces (not cached)."""
        return self._api.list_namespaces()
