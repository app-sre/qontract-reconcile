"""Caching layer for Internal Groups API reads."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel
from qontract_utils.internal_groups_api import Group, NotFoundError
from qontract_utils.internal_groups_api.client import InternalGroupsClient

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedGroup(BaseModel, frozen=True):
    """Serializable group for cache storage."""

    group: Group


class InternalGroupsWorkspaceClient:
    """Layer 2 client: caches group GETs, delegates mutations to Layer 1."""

    def __init__(
        self,
        client_factory: Callable[[], InternalGroupsClient],
        cache: CacheBackend,
        settings: Settings,
        environment_key: str,
    ) -> None:
        self._client_factory = client_factory
        self._client: InternalGroupsClient | None = None
        self.cache = cache
        self.settings = settings
        self.environment_key = environment_key

    def __enter__(self) -> Self:
        self._client = self._client_factory()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _require_client(self) -> InternalGroupsClient:
        if self._client is None:
            raise RuntimeError("InternalGroupsWorkspaceClient is not entered")
        return self._client

    def _cache_key(self, group_name: str) -> str:
        return f"internal_groups:{self.environment_key}:group:{group_name}"

    def _invalidate(self, group_name: str) -> None:
        key = self._cache_key(group_name)
        try:
            with self.cache.lock(key):
                self.cache.delete(key)
        except RuntimeError as err:
            logger.warning(f"Could not acquire lock for {key}: {err}")

    def _get_group_from_shared_cache(self, key: str) -> Group | None:
        """Read cached group from the shared tier only (skip process-local L1)."""
        try:
            value = self.cache.get(key)
            if value is None:
                return None
        except (ConnectionError, TimeoutError) as err:
            logger.warning(
                f"Shared cache unavailable for {key}: {err}",
            )
            return None
        data = self.cache.deserializer(value)
        return CachedGroup.model_validate(data).group

    def _fetch_and_cache(self, key: str, name: str) -> Group | None:
        """Fetch group from API and populate cache (call only while holding the lock)."""
        if cached := self._get_group_from_shared_cache(key):
            return cached
        client = self._require_client()
        try:
            group = client.group(name)
        except NotFoundError:
            return None
        self.cache.set_obj(
            key,
            CachedGroup(group=group),
            ttl=self.settings.internal_groups.group_cache_ttl,
        )
        return group

    def get_group(self, name: str) -> Group | None:
        """Return group by name, or None if not found (cached with distributed locking)."""
        key = self._cache_key(name)
        if cached := self._get_group_from_shared_cache(key):
            return cached

        try:
            with self.cache.lock(key):
                return self._fetch_and_cache(key, name)
        except RuntimeError as err:
            logger.warning(f"Could not acquire lock for {key}: {err}")
            # Lock unavailable: still serve API data, skip cache write.
            try:
                return self._require_client().group(name)
            except NotFoundError:
                return None

    def create_group(self, group: Group) -> Group:
        created = self._require_client().create_group(group)
        self._invalidate(group.name)
        return created

    def update_group(self, group: Group) -> Group:
        updated = self._require_client().update_group(group)
        self._invalidate(group.name)
        return updated

    def delete_group(self, name: str) -> None:
        with contextlib.suppress(NotFoundError):
            self._require_client().delete_group(name)
        self._invalidate(name)
