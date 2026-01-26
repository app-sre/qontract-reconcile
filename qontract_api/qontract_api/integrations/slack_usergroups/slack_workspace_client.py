"""SlackWorkspaceClient: Caching + compute layer for Slack workspace data.

This layer sits between the stateless SlackApi and business logic, providing:
- Two-tier caching (memory + Redis) for Slack data
- Distributed locking for thread-safe cache updates
- Cache updates instead of invalidation (O(1) performance)
- Compute helpers (e.g., get_users_by_ids, get_usergroup_by_handle)
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field
from qontract_utils.slack_api import SlackApi
from qontract_utils.slack_api import SlackChannel as SlackChannelAPI
from qontract_utils.slack_api import SlackUser as SlackUserAPI
from qontract_utils.slack_api import SlackUsergroup as SlackUsergroupAPI

from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroup,
    SlackUsergroupConfig,
)

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = logging.getLogger(__name__)


@runtime_checkable
class TypeWithId(Protocol):
    @property
    def id(self) -> str: ...


T = TypeVar("T", bound=TypeWithId)


class CachedUsers(BaseModel, frozen=True):
    """Cached dict of SlackUserAPI objects (for two-tier cache serialization)."""

    items: list[SlackUserAPI] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackUserAPI]:
        """Convert to dict keyed by ID."""
        return {user.id: user for user in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackUserAPI]) -> CachedUsers:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class CachedUsergroups(BaseModel, frozen=True):
    """Cached dict of SlackUsergroupAPI objects (for two-tier cache serialization)."""

    items: list[SlackUsergroupAPI] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackUsergroupAPI]:
        """Convert to dict keyed by ID."""
        return {ug.id: ug for ug in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackUsergroupAPI]) -> CachedUsergroups:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class CachedChannels(BaseModel, frozen=True):
    """Cached dict of SlackChannelAPI objects (for two-tier cache serialization)."""

    items: list[SlackChannelAPI] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackChannelAPI]:
        """Convert to dict keyed by ID."""
        return {ch.id: ch for ch in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackChannelAPI]) -> CachedChannels:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class SlackUsergroupNotFoundError(Exception):
    """Raised when a Slack usergroup is not found."""


class SlackWorkspaceClient:
    """Caching + compute layer for Slack workspace data.

    Provides:
    - Cached access to users, usergroups, and channels with TTL
    - Distributed locking for thread-safe cache updates
    - Cache updates instead of invalidation for better performance
    - Compute helpers for common operations
    """

    def __init__(
        self,
        slack_api: SlackApi,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize SlackWorkspaceClient.

        Args:
            slack_api: Stateless Slack API client
            cache: Cache backend with two-tier caching (memory + Redis)
            settings: Application settings with Slack config
        """
        self.slack_api = slack_api
        self.cache = cache
        self.settings = settings

    # CACHE KEY HELPERS
    def _cache_key_users(self) -> str:
        """Generate cache key for users."""
        return f"slack:{self.slack_api.workspace_name}:users"

    def _cache_key_usergroups(self) -> str:
        """Generate cache key for usergroups."""
        return f"slack:{self.slack_api.workspace_name}:usergroups"

    def _cache_key_channels(self) -> str:
        """Generate cache key for channels."""
        return f"slack:{self.slack_api.workspace_name}:channels"

    # CACHE OPERATIONS (using two-tier cache from CacheBackend)
    def _get_cached_users(self, cache_key: str) -> dict[str, SlackUserAPI] | None:
        """Get cached users"""
        cached = self.cache.get_obj(cache_key, CachedUsers)
        return cached.to_dict() if cached else None

    def _set_cached_users(
        self, cache_key: str, users: dict[str, SlackUserAPI], ttl: int
    ) -> None:
        """Set cached users"""
        cached = CachedUsers.from_dict(users)
        self.cache.set_obj(cache_key, cached, ttl)

    def _get_cached_usergroups(
        self, cache_key: str
    ) -> dict[str, SlackUsergroupAPI] | None:
        """Get cached usergroups"""
        cached = self.cache.get_obj(cache_key, CachedUsergroups)
        return cached.to_dict() if cached else None

    def _set_cached_usergroups(
        self, cache_key: str, usergroups: dict[str, SlackUsergroupAPI], ttl: int
    ) -> None:
        """Set cached usergroups"""
        cached = CachedUsergroups.from_dict(usergroups)
        self.cache.set_obj(cache_key, cached, ttl)

    def _update_cached_usergroup(
        self, cache_key: str, usergroup_id: str, usergroup: SlackUsergroupAPI, ttl: int
    ) -> None:
        """Update single usergroup in cached dict with distributed lock."""
        try:
            with self.cache.lock(cache_key):
                cached = self._get_cached_usergroups(cache_key)
                if cached:
                    cached[usergroup_id] = usergroup
                    self._set_cached_usergroups(cache_key, cached, ttl)
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock for {cache_key}: {e}")

    def _get_cached_channels(self, cache_key: str) -> dict[str, SlackChannelAPI] | None:
        """Get cached channels"""
        cached = self.cache.get_obj(cache_key, CachedChannels)
        return cached.to_dict() if cached else None

    def _set_cached_channels(
        self, cache_key: str, channels: dict[str, SlackChannelAPI], ttl: int
    ) -> None:
        """Set cached channels"""
        cached = CachedChannels.from_dict(channels)
        self.cache.set_obj(cache_key, cached, ttl)

    # CACHED DATA ACCESS
    def get_users(self) -> dict[str, SlackUserAPI]:
        """Get all users by ID (cached with distributed locking).

        Returns:
            Dict of SlackUserAPI objects by user ID
        """
        cache_key = self._cache_key_users()

        # Try cache first (no lock for reads)
        if cached := self._get_cached_users(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_users(cache_key):
                return cached

            # Fetch from API
            users = {user.id: user for user in self.slack_api.users_list()}

            # Cache
            self._set_cached_users(
                cache_key, users, self.settings.slack.users_cache_ttl
            )

            return users

    def get_usergroups(self) -> dict[str, SlackUsergroupAPI]:
        """Get all usergroups by ID (cached with distributed locking).

        Returns:
            Dict of SlackUsergroupAPI objects by usergroup ID
        """
        cache_key = self._cache_key_usergroups()

        # Try cache first (no lock for reads)
        if cached := self._get_cached_usergroups(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_usergroups(cache_key):
                return cached

            # Fetch from API
            usergroups = {ug.id: ug for ug in self.slack_api.usergroups_list()}

            # Cache
            self._set_cached_usergroups(
                cache_key, usergroups, self.settings.slack.usergroup_cache_ttl
            )

            return usergroups

    def get_channels(self) -> dict[str, SlackChannelAPI]:
        """Get all channels by ID (cached with distributed locking).

        Returns:
            Dict of SlackChannelAPI objects by channel ID
        """
        cache_key = self._cache_key_channels()

        # Try cache first (no lock for reads)
        if cached := self._get_cached_channels(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_channels(cache_key):
                return cached

            # Fetch from API
            channels = {ch.id: ch for ch in self.slack_api.conversations_list()}

            # Cache
            self._set_cached_channels(
                cache_key, channels, self.settings.slack.channels_cache_ttl
            )

            return channels

    # COMPUTE HELPERS
    def _get_usergroup_by_handle(self, handle: str) -> SlackUsergroupAPI | None:
        """Get usergroup by handle.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")

        Returns:
            SlackUsergroupAPI object or None if not found
        """
        usergroups = self.get_usergroups()
        for ug in usergroups.values():
            if ug.handle == handle:
                return ug
        return None

    # PUBLIC HELPERS
    def get_slack_usergroups(self, handles: list[str]) -> list[SlackUsergroup]:
        """Get Slack usergroups by handles.

        Args:
            handles: List of usergroup handles (e.g., ["oncall-team", "dev-team"])

        Returns:
            List of SlackUsergroup objects
        """
        usergroups = [
            ug for ug in self.get_usergroups().values() if ug.handle in handles
        ]
        channel_name_by_id = {
            channel.id: channel.name for channel in self.get_channels().values()
        }
        org_username_by_id = {
            user.id: user.org_username for user in self.get_users().values()
        }

        return [
            SlackUsergroup(
                handle=ug.handle,
                config=SlackUsergroupConfig(
                    description=ug.description,
                    users=[
                        org_username_by_id[pk]
                        for pk in ug.users
                        if pk in org_username_by_id
                    ],
                    channels=[
                        channel_name_by_id[pk]
                        for pk in ug.prefs.channels
                        if pk in channel_name_by_id
                    ],
                ),
            )
            for ug in usergroups
        ]

    def clean_slack_usergroups(
        self, usergroups: Iterable[SlackUsergroup]
    ) -> list[SlackUsergroup]:
        """Clean usergroups by removing non-existing users/channels (efficient batch operation).

        Args:
            usergroups: List of usergroups to clean

        Returns:
            List of cleaned usergroups with only valid users/channels
        """
        # Pre-fetch all data ONCE for all usergroups (2 cache lookups total!)
        # Build O(1) lookup sets ONCE
        valid_org_names = {
            user.org_username for user in self.get_users().values() if not user.deleted
        }
        valid_channel_names = {channel.name for channel in self.get_channels().values()}

        # Filter all usergroups in-memory (very fast!)
        return [
            SlackUsergroup(
                handle=ug.handle,
                config=SlackUsergroupConfig(
                    description=ug.config.description,
                    users=[name for name in ug.config.users if name in valid_org_names],
                    channels=[
                        name
                        for name in ug.config.channels
                        if name in valid_channel_names
                    ],
                ),
            )
            for ug in usergroups
        ]

    def create_usergroup(
        self,
        *,
        handle: str,
        name: str | None = None,
    ) -> SlackUsergroupAPI:
        """Create a new usergroup and add to cache.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            name: Usergroup display name (defaults to handle)

        Returns:
            Created SlackUsergroupAPI object
        """
        created_ug = self.slack_api.usergroup_create(handle=handle, name=name)

        # Add to cache
        try:
            with self.cache.lock(self._cache_key_usergroups()):
                cached = self._get_cached_usergroups(self._cache_key_usergroups())
                if cached:
                    cached[created_ug.id] = created_ug
                    self._set_cached_usergroups(
                        self._cache_key_usergroups(),
                        cached,
                        self.settings.slack.usergroup_cache_ttl,
                    )
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock to cache created usergroup: {e}")

        return created_ug

    def update_usergroup(
        self,
        *,
        handle: str,
        name: str | None = None,
        description: str | None = None,
        channels: Iterable[str] | None = None,
    ) -> SlackUsergroupAPI:
        """Update usergroup and cache (O(1) update, not invalidation).

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            name: Usergroup display name
            description: Short description of the usergroup
            channel_names: List of channel names associate with the usergroup

        Returns:
            Updated SlackUsergroupAPI object
        """
        # Get usergroup by handle
        ug = self._get_usergroup_by_handle(handle)
        if not ug:
            raise SlackUsergroupNotFoundError(f"Usergroup {handle} not found!")

        channel_id_by_name = {
            channel.name: pk for pk, channel in self.get_channels().items()
        }
        updated_ug = self.slack_api.usergroup_update(
            usergroup_id=ug.id,
            name=name,
            description=description,
            channel_ids=[channel_id_by_name[name] for name in channels]
            if channels
            else None,
        )

        # Update cache (not invalidation)
        self._update_cached_usergroup(
            self._cache_key_usergroups(),
            ug.id,
            updated_ug,
            self.settings.slack.usergroup_cache_ttl,
        )

        return updated_ug

    def update_usergroup_users(
        self,
        *,
        handle: str,
        users: Iterable[str],
    ) -> SlackUsergroupAPI:
        """Update usergroup users and cache (O(1) update, not invalidation).

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            users: List of org usernames (will be mapped to Slack user IDs)

        Returns:
            Updated SlackUsergroupAPI object
        """
        # TODO: https://github.com/app-sre/qontract-reconcile/pull/5304#discussion_r2715066336
        # Get usergroup by handle
        ug = self._get_usergroup_by_handle(handle)
        if not ug:
            raise SlackUsergroupNotFoundError(f"Usergroup {handle} not found!")

        all_users = self.get_users()
        # Map user names to IDs
        user_id_by_org_name = {
            user.org_username: user.id
            for user in all_users.values()
            if not user.deleted
        }
        user_ids = [user_id_by_org_name[name] for name in users]

        if user_ids:
            if not ug.is_active():
                # Reactivate usergroup if it was disabled
                updated_ug = self.slack_api.usergroup_enable(usergroup_id=ug.id)
            updated_ug = self.slack_api.usergroup_users_update(
                usergroup_id=ug.id, user_ids=user_ids
            )
        else:
            # Slack API does not allow empty user lists, so we just disable the usergroup
            updated_ug = self.slack_api.usergroup_disable(usergroup_id=ug.id)

        # Update cache (not invalidation)
        self._update_cached_usergroup(
            self._cache_key_usergroups(),
            ug.id,
            updated_ug,
            self.settings.slack.usergroup_cache_ttl,
        )

        return updated_ug
