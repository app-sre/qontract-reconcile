"""Caching layer for Internal Groups API reads."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel
from qontract_utils.internal_groups_api import Group, InternalGroupsApi, NotFoundError

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
        api_factory: Callable[[], InternalGroupsApi],
        cache: CacheBackend,
        settings: Settings,
        environment_key: str,
    ) -> None:
        self._api_factory = api_factory
        self._api: InternalGroupsApi | None = None
        self.cache = cache
        self.settings = settings
        self.environment_key = environment_key

    def __enter__(self) -> Self:
        self._api = self._api_factory()
        self._api.__enter__()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._api is not None:
            self._api.__exit__(exc_type, exc_value, traceback)
            self._api.close()
            self._api = None

    def _cache_key(self, group_name: str) -> str:
        return f"internal_groups:{self.environment_key}:group:{group_name}"

    def _invalidate(self, group_name: str) -> None:
        key = self._cache_key(group_name)
        try:
            with self.cache.lock(key):
                self.cache.delete(key)
        except RuntimeError as err:
            logger.warning(f"Could not acquire lock for {key}: {err}")

    def get_group(self, name: str) -> Group | None:
        """Return group by name, or None if not found."""
        key = self._cache_key(name)
        if cached := self.cache.get_obj(key, CachedGroup):
            return cached.group

        api = self._require_api()
        try:
            group = Group(**api.group(name))
        except NotFoundError:
            return None

        try:
            with self.cache.lock(key):
                if self.cache.get_obj(key, CachedGroup) is None:
                    self.cache.set_obj(
                        key,
                        CachedGroup(group=group),
                        ttl=self.settings.internal_groups.group_cache_ttl,
                    )
        except RuntimeError as err:
            logger.warning(f"Could not cache group {name}: {err}")
        return group

    def create_group(self, group: Group) -> Group:
        api = self._require_api()
        created = Group(**api.create_group(group.model_dump(by_alias=True)))
        self._invalidate(group.name)
        return created

    def update_group(self, group: Group) -> Group:
        api = self._require_api()
        updated = Group(**api.update_group(group.name, group.model_dump(by_alias=True)))
        self._invalidate(group.name)
        return updated

    def delete_group(self, name: str) -> None:
        api = self._require_api()
        with contextlib.suppress(NotFoundError):
            api.delete_group(name)
        self._invalidate(name)

    def _require_api(self) -> InternalGroupsApi:
        if self._api is None:
            raise RuntimeError("InternalGroupsWorkspaceClient is not entered")
        return self._api
