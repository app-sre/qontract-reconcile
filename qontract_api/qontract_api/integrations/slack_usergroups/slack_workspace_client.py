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
from qontract_utils.slack_api import SlackApi, SlackChannel, SlackUser, SlackUsergroup

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
    """Cached dict of SlackUser objects (for two-tier cache serialization)."""

    items: list[SlackUser] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackUser]:
        """Convert to dict keyed by ID."""
        return {user.id: user for user in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackUser]) -> CachedUsers:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class CachedUsergroups(BaseModel, frozen=True):
    """Cached dict of SlackUsergroup objects (for two-tier cache serialization)."""

    items: list[SlackUsergroup] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackUsergroup]:
        """Convert to dict keyed by ID."""
        return {ug.id: ug for ug in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackUsergroup]) -> CachedUsergroups:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class CachedChannels(BaseModel, frozen=True):
    """Cached dict of SlackChannel objects (for two-tier cache serialization)."""

    items: list[SlackChannel] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackChannel]:
        """Convert to dict keyed by ID."""
        return {ch.id: ch for ch in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackChannel]) -> CachedChannels:
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
    def _get_cached_users(self, cache_key: str) -> dict[str, SlackUser] | None:
        """Get cached users"""
        cached = self.cache.get_obj(cache_key, CachedUsers)
        return cached.to_dict() if cached else None

    def _get_cached_usergroups(
        self, cache_key: str
    ) -> dict[str, SlackUsergroup] | None:
        """Get cached usergroups"""
        cached = self.cache.get_obj(cache_key, CachedUsergroups)
        return cached.to_dict() if cached else None

    def _get_cached_channels(self, cache_key: str) -> dict[str, SlackChannel] | None:
        """Get cached channels"""
        cached = self.cache.get_obj(cache_key, CachedChannels)
        return cached.to_dict() if cached else None

    def _set_cached_users(
        self, cache_key: str, users: dict[str, SlackUser], ttl: int
    ) -> None:
        """Set cached users"""
        cached = CachedUsers.from_dict(users)
        self.cache.set_obj(cache_key, cached, ttl)

    def _set_cached_usergroups(
        self, cache_key: str, usergroups: dict[str, SlackUsergroup], ttl: int
    ) -> None:
        """Set cached usergroups"""
        cached = CachedUsergroups.from_dict(usergroups)
        self.cache.set_obj(cache_key, cached, ttl)

    def _set_cached_channels(
        self, cache_key: str, channels: dict[str, SlackChannel], ttl: int
    ) -> None:
        """Set cached channels"""
        cached = CachedChannels.from_dict(channels)
        self.cache.set_obj(cache_key, cached, ttl)

    def _update_cached_usergroup(
        self, cache_key: str, usergroup_id: str, usergroup: SlackUsergroup, ttl: int
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

    # CACHED DATA ACCESS
    def get_users(self) -> dict[str, SlackUser]:
        """Get all users by ID (cached with distributed locking).

        Returns:
            Dict of SlackUser objects by user ID
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

    def get_usergroups(self) -> dict[str, SlackUsergroup]:
        """Get all usergroups by ID (cached with distributed locking).

        Returns:
            Dict of SlackUsergroup objects by usergroup ID
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

    def get_channels(self) -> dict[str, SlackChannel]:
        """Get all channels by ID (cached with distributed locking).

        Returns:
            Dict of SlackChannel objects by channel ID
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
    def get_users_by_ids(self, user_ids: Iterable[str]) -> list[SlackUser]:
        """Get users by IDs (subset of all users).

        Args:
            user_ids: List of user IDs

        Returns:
            List of SlackUser objects
        """
        all_users = self.get_users()
        return [all_users[uid] for uid in user_ids if uid in all_users]

    def get_users_by_org_names(self, org_user_names: Iterable[str]) -> list[SlackUser]:
        """Get active (non-deleted) users by organization usernames.

        Args:
            org_user_names: List of organization usernames
        Returns:
            List of SlackUser objects
        """
        result = []
        for user in self.get_users().values():
            if user.deleted:
                continue
            if user.org_username in org_user_names:
                result.append(user)
        return result

    def get_usergroup_by_id(self, usergroup_id: str) -> SlackUsergroup | None:
        """Get usergroup by ID.

        Args:
            usergroup_id: Usergroup ID

        Returns:
            SlackUsergroup object or None if not found
        """
        usergroups = self.get_usergroups()
        return usergroups.get(usergroup_id)

    def get_usergroup_by_handle(self, handle: str) -> SlackUsergroup | None:
        """Get usergroup by handle.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")

        Returns:
            SlackUsergroup object or None if not found
        """
        usergroups = self.get_usergroups()
        for ug in usergroups.values():
            if ug.handle == handle:
                return ug
        return None

    def get_channels_by_ids(self, channel_ids: Iterable[str]) -> list[SlackChannel]:
        """Get channels by IDs (subset of all channels).

        Args:
            channel_ids: List of channel IDs

        Returns:
            List of SlackChannel objects
        """
        all_channels = self.get_channels()
        return [all_channels[cid] for cid in channel_ids if cid in all_channels]

    def get_channels_by_names(self, channel_names: Iterable[str]) -> list[SlackChannel]:
        """Get channels by names.

        Args:
            channel_names: List of channel names (without # prefix)

        Returns:
            List of SlackChannel objects
        """
        return [
            channel
            for channel in self.get_channels().values()
            if channel.name in channel_names
        ]

    def create_usergroup(
        self,
        *,
        handle: str,
        name: str | None = None,
    ) -> SlackUsergroup:
        """Create a new usergroup and add to cache.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            name: Usergroup display name (defaults to handle)

        Returns:
            Created SlackUsergroup object
        """
        created_ug = self.slack_api.usergroups_create(handle=handle, name=name)

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
    ) -> SlackUsergroup:
        """Update usergroup and cache (O(1) update, not invalidation).

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            name: Usergroup display name
            description: Short description of the usergroup
            channel_names: List of channel names associate with the usergroup

        Returns:
            Updated SlackUsergroup object
        """
        # Get usergroup by handle
        ug = self.get_usergroup_by_handle(handle)
        if not ug:
            raise SlackUsergroupNotFoundError(f"Usergroup {handle} not found!")

        updated_ug = self.slack_api.usergroups_update(
            usergroup_id=ug.id,
            name=name,
            description=description,
            channel_ids=[c.id for c in self.get_channels_by_names(channels)]
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
        users: list[str],
    ) -> SlackUsergroup:
        """Update usergroup users and cache (O(1) update, not invalidation).

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            users: List of user IDs

        Returns:
            Updated SlackUsergroup object
        """
        # Get usergroup by handle
        ug = self.get_usergroup_by_handle(handle)
        if not ug:
            raise SlackUsergroupNotFoundError(f"Usergroup {handle} not found!")

        updated_ug = self.slack_api.usergroups_users_update(
            usergroup_id=ug.id,
            user_ids=users,
        )

        # Update cache (not invalidation)
        self._update_cached_usergroup(
            self._cache_key_usergroups(),
            ug.id,
            updated_ug,
            self.settings.slack.usergroup_cache_ttl,
        )

        return updated_ug
