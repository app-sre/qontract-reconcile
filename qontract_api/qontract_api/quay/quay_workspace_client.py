"""QuayWorkspaceClient: Caching layer for Quay organization repository data.

Layer 2 (Cache + Compute) following ADR-014. Sits between the stateless
QuayApi (Layer 1) and business logic (Layer 3), providing:
- Two-tier caching (memory + Redis) with TTL
- Distributed locking for thread-safe cache updates
- Cache invalidation after each successful mutation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, Field
from qontract_utils.quay_api import QuayApi, QuayRepo

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedRepos(BaseModel, frozen=True):
    """Serializable wrapper for a list of QuayRepo objects."""

    items: list[QuayRepo] = Field(default_factory=list)


class QuayWorkspaceClient:
    """Caching layer for Quay organization repository data.

    Provides:
    - Cached access to repository lists with TTL
    - Distributed locking for thread-safe cache updates
    - Cache invalidation after each successful mutation
    """

    def __init__(
        self,
        quay_api: QuayApi,
        base_url: str,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        self.quay_api = quay_api
        self._base_url = base_url.rstrip("/")
        self.cache = cache
        self.settings = settings

    def _cache_key_repos(self) -> str:
        return f"quay:{self._base_url}:{self.quay_api.org}:repos"

    # ------------------------------------------------------------------
    # Cached read
    # ------------------------------------------------------------------

    def get_repos(self) -> list[QuayRepo]:
        """List all repositories in the organization (cached).

        Returns:
            List of QuayRepo objects
        """
        cache_key = self._cache_key_repos()

        cached = self.cache.get_obj(cache_key, CachedRepos)
        if cached:
            return cached.items

        with self.cache.lock(cache_key):
            cached = self.cache.get_obj(cache_key, CachedRepos)
            if cached:
                return cached.items

            repos = self.quay_api.list_images()
            self.cache.set_obj(
                cache_key,
                CachedRepos(items=repos),
                self.settings.quay.repos_cache_ttl,
            )
            return repos

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def repo_create(self, repo_name: str, description: str, *, public: bool) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_create(repo_name, description, public=public)
            self.cache.delete(cache_key)

    def repo_delete(self, repo_name: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_delete(repo_name)
            self.cache.delete(cache_key)

    def repo_update_description(self, repo_name: str, description: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_update_description(repo_name, description)
            self.cache.delete(cache_key)

    def repo_make_public(self, repo_name: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_make_public(repo_name)
            self.cache.delete(cache_key)

    def repo_make_private(self, repo_name: str) -> None:
        cache_key = self._cache_key_repos()
        with self.cache.lock(cache_key):
            self.quay_api.repo_make_private(repo_name)
            self.cache.delete(cache_key)

    def close(self) -> None:
        self.quay_api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
