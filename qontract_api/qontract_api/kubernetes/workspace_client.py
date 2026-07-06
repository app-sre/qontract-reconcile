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


class CachedNamespaceExists(BaseModel, frozen=True):
    """Cached namespace existence check result."""

    exists: bool


class KubernetesWorkspaceClient:
    """Caching layer for Kubernetes namespace operations.

    Uses double-check locking for thread-safe cache updates.
    Mutations (create/delete) invalidate the relevant cache entries.
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

    def _cache_key_namespace_exists(self, name: str) -> str:
        return f"kubernetes:{self._cluster_name}:namespace:{name}:exists"

    def _invalidate_namespace_cache(self, name: str) -> None:
        self._cache.delete(self._cache_key_namespace_exists(name))

    def namespace_exists(self, name: str) -> bool:
        """Check if a namespace exists (cached with double-check locking)."""
        cache_key = self._cache_key_namespace_exists(name)

        if cached := self._cache.get_obj(cache_key, CachedNamespaceExists):
            return cached.exists

        with self._cache.lock(cache_key):
            if cached := self._cache.get_obj(cache_key, CachedNamespaceExists):
                return cached.exists

            exists = self._api.namespace_exists(name)
            self._cache.set_obj(
                cache_key,
                CachedNamespaceExists(exists=exists),
                self._settings.kubernetes.namespace_cache_ttl,
            )
            return exists

    def create_namespace(self, name: str) -> Namespace:
        """Create a namespace and invalidate cache."""
        result = self._api.create_namespace(name)
        self._invalidate_namespace_cache(name)
        return result

    def delete_namespace(self, name: str) -> None:
        """Delete a namespace and invalidate cache."""
        self._api.delete_namespace(name)
        self._invalidate_namespace_cache(name)

    def list_namespaces(self) -> list[Namespace]:
        """List all namespaces (not cached)."""
        return self._api.list_namespaces()
